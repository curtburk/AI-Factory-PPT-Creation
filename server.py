#!/usr/bin/env python3
"""
Deck Factory v2 -- Server
==========================
FastAPI application. Calls vLLM directly via HTTP with constrained JSON output.
Deterministic Node.js renderer produces .pptx files.

No NemoClaw. No Ollama. No SSH.
"""

import asyncio
import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from schemas import DeckPlan, get_deck_schema
from prompts import SYSTEM_PROMPT

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"
LOGOS_DIR = BASE_DIR / "logos"
TEMPLATES_DIR = BASE_DIR / "templates"

OUTPUT_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
LOGOS_DIR.mkdir(exist_ok=True)

VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen3.6-27B-FP8")
RENDERER = BASE_DIR / "render_deck.js"
MAX_HISTORY_TURNS = 8  # keep last N user/assistant pairs

# ── Logging ───────────────────────────────────────────────────────────────────

request_id_var: ContextVar[str] = ContextVar("request_id", default="startup")


class RequestFormatter(logging.Formatter):
    def format(self, record):
        record.request_id = request_id_var.get("no_req")
        return super().format(record)


LOG_FORMAT = "[%(asctime)s.%(msecs)03d] [%(request_id)s] [%(name)s] [%(levelname)s] %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

formatter = RequestFormatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

# File handler (rotating, 10MB, 5 backups)
file_handler = logging.handlers.RotatingFileHandler(
    LOGS_DIR / "deck_factory.log",
    maxBytes=10_000_000,
    backupCount=5,
)
file_handler.setFormatter(formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

# Module loggers
api_log = logging.getLogger("API")
vllm_log = logging.getLogger("VLLM")
render_log = logging.getLogger("RENDER")
validate_log = logging.getLogger("VALIDATE")
session_log = logging.getLogger("SESSION")
startup_log = logging.getLogger("STARTUP")

# ── Exceptions ────────────────────────────────────────────────────────────────


class DeckFactoryError(Exception):
    def __init__(self, stage: str, message: str, details: dict = None):
        self.stage = stage
        self.message = message
        self.details = details or {}
        super().__init__(message)


class VLLMConnectionError(DeckFactoryError):
    pass


class VLLMResponseError(DeckFactoryError):
    pass


class ValidationError(DeckFactoryError):
    pass


class RendererError(DeckFactoryError):
    pass


# ── Session Store ─────────────────────────────────────────────────────────────

sessions: dict[str, list[dict]] = {}


def get_or_create_session(session_id: str) -> list[dict]:
    if session_id not in sessions:
        sessions[session_id] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        session_log.info(f"Session created: {session_id}")
    return sessions[session_id]


def trim_session(session_id: str):
    """Keep system prompt + last MAX_HISTORY_TURNS user/assistant pairs."""
    history = sessions.get(session_id, [])
    if len(history) <= 1 + MAX_HISTORY_TURNS * 2:
        return

    before = len(history)
    # Always keep index 0 (system prompt)
    system = history[0]
    recent = history[-(MAX_HISTORY_TURNS * 2):]
    sessions[session_id] = [system] + recent
    after = len(sessions[session_id])
    session_log.debug(f"Session trimmed: {before} -> {after} messages")


# ── vLLM Client ───────────────────────────────────────────────────────────────

async def check_vllm_health(max_retries: int = 60, delay: float = 5.0):
    """Block until vLLM is ready. Log every attempt."""
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{VLLM_URL}/health")
                if r.status_code == 200:
                    startup_log.info(f"vLLM healthy (attempt {attempt})")
                    # Check what models are loaded
                    models_resp = await client.get(f"{VLLM_URL}/v1/models")
                    if models_resp.status_code == 200:
                        model_data = models_resp.json()
                        loaded = [m["id"] for m in model_data.get("data", [])]
                        startup_log.info(f"Models loaded: {loaded}")
                    return True
                else:
                    startup_log.warning(
                        f"vLLM returned {r.status_code} (attempt {attempt}/{max_retries})"
                    )
        except httpx.ConnectError:
            startup_log.debug(f"vLLM not reachable (attempt {attempt}/{max_retries})")
        except Exception as e:
            startup_log.debug(
                f"vLLM check failed: {type(e).__name__}: {e} "
                f"(attempt {attempt}/{max_retries})"
            )
        await asyncio.sleep(delay)

    startup_log.critical(f"vLLM not available after {max_retries} attempts ({max_retries * delay:.0f}s)")
    raise VLLMConnectionError("startup", "vLLM did not become healthy")


async def call_vllm(messages: list[dict], req_id: str) -> str:
    """
    Call vLLM's /v1/chat/completions with constrained JSON output.
    Returns the raw JSON string from the model.
    """
    schema = get_deck_schema()

    payload = {
        "model": VLLM_MODEL,
        "messages": messages,
        "max_tokens": 32768,
        "temperature": 0.7,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "deck_plan",
                "strict": True,
                "schema": schema,
            },
        },
    }

    total_chars = sum(len(m.get("content", "")) for m in messages)
    vllm_log.info(
        f"Sending request: {len(messages)} messages, {total_chars} total chars, "
        f"max_tokens=16384, schema_keys={list(schema.get('properties', {}).keys())}"
    )

    start = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{VLLM_URL}/v1/chat/completions",
                json=payload,
            )
    except httpx.ConnectError as e:
        vllm_log.error(f"Connection failed: {e}")
        raise VLLMConnectionError(
            "vllm_call", f"Cannot connect to vLLM at {VLLM_URL}",
            {"url": VLLM_URL, "error": str(e)},
        )
    except httpx.ReadTimeout as e:
        elapsed = time.monotonic() - start
        vllm_log.error(f"Request timed out after {elapsed:.1f}s")
        raise VLLMResponseError(
            "vllm_call", "vLLM request timed out (300s)",
            {"elapsed": elapsed, "timeout": 300},
        )
    except Exception as e:
        vllm_log.error(f"Unexpected error: {type(e).__name__}: {e}")
        raise VLLMResponseError(
            "vllm_call", f"Unexpected error: {type(e).__name__}",
            {"error": str(e)},
        )

    elapsed = time.monotonic() - start

    if resp.status_code != 200:
        body = resp.text[:500]
        vllm_log.error(
            f"vLLM returned {resp.status_code} ({elapsed:.2f}s). "
            f"Body: {body}"
        )
        raise VLLMResponseError(
            "vllm_call", f"vLLM returned HTTP {resp.status_code}",
            {"status_code": resp.status_code, "body": body, "elapsed": elapsed},
        )

    data = resp.json()
    choices = data.get("choices", [])

    if not choices:
        vllm_log.error(f"vLLM returned empty choices ({elapsed:.2f}s). Full response: {json.dumps(data)[:500]}")
        raise VLLMResponseError(
            "vllm_call", "vLLM returned no choices",
            {"response": json.dumps(data)[:500], "elapsed": elapsed},
        )

    choice = choices[0]
    content = choice.get("message", {}).get("content", "")
    finish_reason = choice.get("finish_reason", "unknown")
    usage = data.get("usage", {})

    vllm_log.info(
        f"Response received: {len(content)} chars, {elapsed:.2f}s, "
        f"finish_reason={finish_reason}, "
        f"prompt_tokens={usage.get('prompt_tokens', '?')}, "
        f"completion_tokens={usage.get('completion_tokens', '?')}, "
        f"total_tokens={usage.get('total_tokens', '?')}"
    )

    if not content:
        vllm_log.error(
            f"Empty content. finish_reason={finish_reason}, usage={usage}"
        )
        raise VLLMResponseError(
            "vllm_call", "vLLM returned empty content",
            {"finish_reason": finish_reason, "usage": usage, "elapsed": elapsed},
        )

    if finish_reason == "length":
        vllm_log.warning(
            f"Output may be truncated (finish_reason=length). "
            f"completion_tokens={usage.get('completion_tokens', '?')}"
        )

    return content


# ── Color Override ────────────────────────────────────────────────────────────

def apply_user_colors(bg: str = None, text: str = None, highlight: str = None):
    """Write brand.json with user-selected colors. Called before renderer."""
    brand_path = BASE_DIR / "brand.json"

    colors = {}
    if bg:
        b = bg.lstrip("#")
        colors["darkBg"] = b
        colors["lightBg"] = b
    if text:
        t = text.lstrip("#")
        colors["darkText"] = t
        colors["lightText"] = "FFFFFF"
        colors["mutedText"] = t
    if highlight:
        h = highlight.lstrip("#")
        colors["primary"] = h
        colors["secondary"] = h
        colors["accent"] = h
        colors["highlight"] = h
        colors["chartColors"] = [h]

    if colors:
        brand = {"colors": colors, "fonts": {"headerFont": "Georgia", "bodyFont": "Calibri"}}
        brand_path.write_text(json.dumps(brand, indent=2))
        render_log.debug(f"Brand colors written: {colors}")
    elif brand_path.exists():
        # No user colors, remove brand overrides
        brand_path.write_text(json.dumps({"colors": {}, "fonts": {}}, indent=2))
        render_log.debug("Brand colors cleared")


# ── Renderer ──────────────────────────────────────────────────────────────────

def run_renderer(deck_json: dict, job_id: str) -> Path:
    """Run render_deck.js to produce a .pptx file."""
    input_path = OUTPUT_DIR / f"{job_id}_plan.json"
    output_path = OUTPUT_DIR / f"{job_id}.pptx"

    # Write the JSON plan
    input_path.write_text(json.dumps(deck_json, indent=2))
    render_log.info(f"Deck plan written: {input_path} ({input_path.stat().st_size:,} bytes)")

    start = time.monotonic()

    try:
        result = subprocess.run(
            ["node", str(RENDERER), str(input_path), str(output_path)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(BASE_DIR),
        )
    except subprocess.TimeoutExpired:
        render_log.error(f"Renderer timed out after 30s. Input: {input_path}")
        raise RendererError("render", "Renderer timed out after 30s", {"input": str(input_path)})
    except FileNotFoundError:
        render_log.error("Node.js not found. Is node installed?")
        raise RendererError("render", "node binary not found", {})

    elapsed = time.monotonic() - start

    if result.stdout.strip():
        render_log.debug(f"Renderer stdout: {result.stdout.strip()}")
    if result.stderr.strip():
        render_log.warning(f"Renderer stderr: {result.stderr.strip()}")

    if result.returncode != 0:
        render_log.error(
            f"Renderer failed (exit {result.returncode}, {elapsed:.2f}s). "
            f"stdout: {result.stdout[:500]} | stderr: {result.stderr[:500]}"
        )
        raise RendererError(
            "render",
            f"Renderer exited with code {result.returncode}",
            {
                "exit_code": result.returncode,
                "stdout": result.stdout[:500],
                "stderr": result.stderr[:500],
                "input": str(input_path),
            },
        )

    if not output_path.exists():
        render_log.error(f"Output file missing after successful exit: {output_path}")
        raise RendererError("render", "Output file not created", {"output": str(output_path)})

    file_size = output_path.stat().st_size
    render_log.info(f"Renderer complete: {elapsed:.2f}s, {file_size:,} bytes, {output_path.name}")

    return output_path


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Deck Factory v2")


# Error handlers
@app.exception_handler(DeckFactoryError)
async def deck_error_handler(request: Request, exc: DeckFactoryError):
    api_log.error(f"[{exc.stage}] {exc.message} | details={exc.details}")
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "stage": exc.stage,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    api_log.critical(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "stage": "unknown",
            "message": "Internal server error",
            "details": {"type": type(exc).__name__, "message": str(exc)},
        },
    )


# Startup
@app.on_event("startup")
async def on_startup():
    startup_log.info("Deck Factory v2 starting...")
    startup_log.info(f"vLLM URL: {VLLM_URL}")
    startup_log.info(f"vLLM Model: {VLLM_MODEL}")
    startup_log.info(f"Renderer: {RENDERER}")
    startup_log.info(f"Output dir: {OUTPUT_DIR}")
    startup_log.info(f"Logs dir: {LOGS_DIR}")

    # Check renderer
    if not RENDERER.exists():
        startup_log.error(f"Renderer not found: {RENDERER}")
        raise RuntimeError(f"Renderer not found: {RENDERER}")

    # Check node
    try:
        node_version = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=5,
        )
        startup_log.info(f"Node.js version: {node_version.stdout.strip()}")
    except Exception as e:
        startup_log.error(f"Node.js not available: {e}")
        raise RuntimeError(f"Node.js not available: {e}")

    # Wait for vLLM (non-blocking -- allow the app to start even if vLLM is slow)
    try:
        await check_vllm_health(max_retries=60, delay=5.0)
    except VLLMConnectionError:
        startup_log.warning("vLLM not available at startup. Requests will fail until it's ready.")


# ── Request Models ────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    prompt: str
    session_id: str = ""
    deck_title: str = ""
    bg_color: str = ""
    text_color: str = ""
    highlight_color: str = ""


class RefineRequest(BaseModel):
    prompt: str
    session_id: str
    deck_title: str = ""
    bg_color: str = ""
    text_color: str = ""
    highlight_color: str = ""


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/generate")
async def generate_deck(req: GenerateRequest):
    req_id = f"gen_{uuid.uuid4().hex[:8]}"
    request_id_var.set(req_id)

    session_id = req.session_id or f"session_{uuid.uuid4().hex[:8]}"
    api_log.info(
        f"Generate request: session={session_id}, prompt_len={len(req.prompt)}, "
        f"bg={req.bg_color or 'none'}, text={req.text_color or 'none'}, "
        f"highlight={req.highlight_color or 'none'}, "
        f"has_logo={Path(LOGOS_DIR / 'current_logo.png').exists()}"
    )

    start = time.monotonic()

    # Build messages
    history = get_or_create_session(session_id)
    history.append({"role": "user", "content": req.prompt})

    # Call vLLM
    content = await call_vllm(history, req_id)

    # Validate with Pydantic
    validate_log.info(f"Validating response ({len(content)} chars)...")
    try:
        deck_plan = DeckPlan.model_validate_json(content)
        slide_layouts = [s.layout for s in deck_plan.slides]
        validate_log.info(
            f"Validation passed: {len(deck_plan.slides)} slides, "
            f"layouts={slide_layouts}"
        )
    except Exception as e:
        validate_log.error(
            f"Validation failed: {e}. Raw content (first 1000 chars): {content[:1000]}"
        )
        raise ValidationError(
            "validate",
            f"Model output failed schema validation: {e}",
            {"error": str(e), "content_preview": content[:1000]},
        )

    # Add assistant response to history
    history.append({"role": "assistant", "content": content})
    trim_session(session_id)

    # Apply user colors
    apply_user_colors(
        bg=req.bg_color or None,
        text=req.text_color or None,
        highlight=req.highlight_color or None,
    )

    # Render
    deck_dict = json.loads(content)

    # Override title if user specified one
    if req.deck_title.strip():
        user_title = req.deck_title.strip()
        if deck_dict.get("meta"):
            deck_dict["meta"]["title"] = user_title
        for slide in deck_dict.get("slides", []):
            if slide.get("layout") == "title_slide":
                slide["title"] = user_title
                break
        api_log.info(f"User title override applied: {user_title}")

    job_id = f"deck_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    output_path = run_renderer(deck_dict, job_id)

    elapsed = time.monotonic() - start
    api_log.info(f"Generate complete: {elapsed:.2f}s total, job_id={job_id}")

    return {
        "job_id": job_id,
        "session_id": session_id,
        "slides": len(deck_plan.slides),
        "layouts": [s.layout for s in deck_plan.slides],
        "elapsed": round(elapsed, 2),
        "download_url": f"/api/download/{job_id}",
    }


@app.post("/api/refine")
async def refine_deck(req: RefineRequest):
    req_id = f"ref_{uuid.uuid4().hex[:8]}"
    request_id_var.set(req_id)

    if req.session_id not in sessions:
        api_log.warning(f"Refine request for unknown session: {req.session_id}")
        raise HTTPException(status_code=404, detail="Session not found. Generate a deck first.")

    api_log.info(
        f"Refine request: session={req.session_id}, prompt_len={len(req.prompt)}, "
        f"history_len={len(sessions[req.session_id])}"
    )

    start = time.monotonic()

    # Append refinement to history
    history = sessions[req.session_id]
    history.append({"role": "user", "content": req.prompt})

    # Call vLLM with full history
    content = await call_vllm(history, req_id)

    # Validate
    validate_log.info(f"Validating refined response ({len(content)} chars)...")
    try:
        deck_plan = DeckPlan.model_validate_json(content)
        slide_layouts = [s.layout for s in deck_plan.slides]
        validate_log.info(
            f"Validation passed: {len(deck_plan.slides)} slides, "
            f"layouts={slide_layouts}"
        )
    except Exception as e:
        validate_log.error(
            f"Validation failed: {e}. Raw content (first 1000 chars): {content[:1000]}"
        )
        raise ValidationError(
            "validate",
            f"Refined output failed schema validation: {e}",
            {"error": str(e), "content_preview": content[:1000]},
        )

    # Update history
    history.append({"role": "assistant", "content": content})
    trim_session(req.session_id)

    # Apply colors
    apply_user_colors(
        bg=req.bg_color or None,
        text=req.text_color or None,
        highlight=req.highlight_color or None,
    )

    # Render
    deck_dict = json.loads(content)

    # Override title if user specified one
    if req.deck_title.strip():
        user_title = req.deck_title.strip()
        if deck_dict.get("meta"):
            deck_dict["meta"]["title"] = user_title
        for slide in deck_dict.get("slides", []):
            if slide.get("layout") == "title_slide":
                slide["title"] = user_title
                break
        api_log.info(f"User title override applied: {user_title}")

    job_id = f"deck_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    output_path = run_renderer(deck_dict, job_id)

    elapsed = time.monotonic() - start
    api_log.info(f"Refine complete: {elapsed:.2f}s total, job_id={job_id}")

    return {
        "job_id": job_id,
        "session_id": req.session_id,
        "slides": len(deck_plan.slides),
        "layouts": [s.layout for s in deck_plan.slides],
        "elapsed": round(elapsed, 2),
        "download_url": f"/api/download/{job_id}",
    }


@app.post("/api/upload-logo")
async def upload_logo(file: UploadFile = File(...)):
    req_id = f"logo_{uuid.uuid4().hex[:8]}"
    request_id_var.set(req_id)

    api_log.info(f"Logo upload: filename={file.filename}, content_type={file.content_type}")

    # Validate file type
    allowed_types = {"image/png", "image/jpeg", "image/svg+xml", "image/webp"}
    if file.content_type not in allowed_types:
        api_log.warning(f"Rejected logo upload: {file.content_type}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Use PNG, JPG, SVG, or WebP.",
        )

    # Save as current_logo.png (convert if needed via sharp later)
    logo_path = LOGOS_DIR / "current_logo.png"
    try:
        contents = await file.read()
        logo_path.write_bytes(contents)
        file_size = logo_path.stat().st_size
        api_log.info(f"Logo saved: {logo_path} ({file_size:,} bytes)")
    except Exception as e:
        api_log.error(f"Failed to save logo: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save logo: {e}")

    return {"status": "ok", "path": str(logo_path), "size": file_size}


@app.delete("/api/logo")
async def delete_logo():
    logo_path = LOGOS_DIR / "current_logo.png"
    if logo_path.exists():
        logo_path.unlink()
        api_log.info("Logo deleted")
        return {"status": "ok", "message": "Logo removed"}
    return {"status": "ok", "message": "No logo to remove"}


@app.get("/api/download/{job_id}")
async def download_deck(job_id: str):
    req_id = f"dl_{uuid.uuid4().hex[:8]}"
    request_id_var.set(req_id)

    output_path = OUTPUT_DIR / f"{job_id}.pptx"
    if not output_path.exists():
        api_log.warning(f"Download requested for missing file: {job_id}")
        raise HTTPException(status_code=404, detail="File not found")

    file_size = output_path.stat().st_size
    api_log.info(f"Serving download: {job_id} ({file_size:,} bytes)")

    return FileResponse(
        path=str(output_path),
        filename=f"{job_id}.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    history = sessions[session_id]
    # Return only user/assistant messages (not system prompt)
    turns = [m for m in history if m["role"] != "system"]
    return {"session_id": session_id, "turns": len(turns), "messages": turns}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        session_log.info(f"Session deleted: {session_id}")
    return {"status": "ok"}


@app.get("/api/health")
async def health():
    # Check vLLM
    vllm_ok = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{VLLM_URL}/health")
            vllm_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "status": "ok" if vllm_ok else "degraded",
        "vllm": "healthy" if vllm_ok else "unreachable",
        "vllm_url": VLLM_URL,
        "model": VLLM_MODEL,
        "active_sessions": len(sessions),
        "logo_uploaded": Path(LOGOS_DIR / "current_logo.png").exists(),
    }


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/static/header-logo.png")
async def serve_header_logo():
    logo_path = BASE_DIR / "logos" / "header_logo.png"
    if logo_path.exists():
        return FileResponse(path=str(logo_path), media_type="image/png")
    raise HTTPException(status_code=404, detail="Header logo not found")


@app.get("/")
async def serve_frontend():
    index_path = TEMPLATES_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text())
    return HTMLResponse(content="<h1>Deck Factory v2</h1><p>Frontend not found.</p>")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888, log_level="info")