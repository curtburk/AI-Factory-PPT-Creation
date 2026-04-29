#!/bin/bash
# =============================================================================
# HP Deck Factory - Start Script
# Starts vLLM inference engine and the web application
# =============================================================================
set -e

VLLM_CONTAINER_NAME="deck-factory-vllm"
VLLM_IMAGE="vllm/vllm-openai:cu130-nightly"
VLLM_MODEL="Qwen/Qwen3.6-27B-FP8"
VLLM_PORT=8000
APP_PORT=8888
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Pre-flight checks ───────────────────────────────────────────────────────

echo ""
echo "=============================================="
echo "  HP Deck Factory - Preflight Checks"
echo "=============================================="
echo ""

# Check Docker is running
if ! docker info &>/dev/null; then
    echo "  [FAIL] Docker daemon is not running."
    echo "         Start it with: sudo systemctl start docker"
    echo ""
    exit 1
fi
echo "  [OK] Docker is running"

# Check NVIDIA GPU
if ! nvidia-smi &>/dev/null; then
    echo "  [FAIL] NVIDIA GPU not detected."
    echo "         Check driver installation with: nvidia-smi"
    echo ""
    exit 1
fi
GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
echo "  [OK] GPU detected: $GPU_NAME"

# Check Node.js
if ! command -v node &>/dev/null; then
    echo "  [FAIL] Node.js not found."
    echo "         Install with: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash - && sudo apt install nodejs"
    echo ""
    exit 1
fi
NODE_VERSION=$(node --version)
echo "  [OK] Node.js $NODE_VERSION"

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "  [FAIL] Python3 not found."
    echo ""
    exit 1
fi
PYTHON_VERSION=$(python3 --version 2>&1)
echo "  [OK] $PYTHON_VERSION"

# Check Node dependencies
if [ ! -d "$SCRIPT_DIR/node_modules" ]; then
    echo "  [INFO] Installing Node.js dependencies..."
    cd "$SCRIPT_DIR" && npm install --production 2>&1 | tail -1
fi
echo "  [OK] Node.js dependencies installed"

# Check Python dependencies
if ! python3 -c "import fastapi, httpx, pydantic" 2>/dev/null; then
    echo "  [INFO] Installing Python dependencies..."
    pip install -r "$SCRIPT_DIR/requirements.txt" -q
fi
echo "  [OK] Python dependencies installed"

# Check vLLM image exists
if ! docker image inspect "$VLLM_IMAGE" &>/dev/null; then
    echo "  [FAIL] vLLM Docker image not found: $VLLM_IMAGE"
    echo "         Pull it with: docker pull $VLLM_IMAGE"
    echo ""
    exit 1
fi
echo "  [OK] vLLM Docker image available"

# Check HuggingFace cache
echo "  [OK] HF cache: $HF_CACHE"

echo ""
echo "  All checks passed."
echo ""

# ── Start or reuse vLLM ──────────────────────────────────────────────────────

VLLM_RUNNING=false

# Check if vLLM container is already running and healthy
if docker ps --format '{{.Names}}' | grep -q "^${VLLM_CONTAINER_NAME}$"; then
    if curl -sf "http://localhost:${VLLM_PORT}/health" &>/dev/null; then
        echo ""
        echo "=============================================="
        echo "  vLLM already running and healthy - skipping startup"
        echo "=============================================="
        echo ""
        VLLM_RUNNING=true
    else
        echo "  vLLM container exists but not healthy. Restarting..."
        docker rm -f "$VLLM_CONTAINER_NAME" &>/dev/null
    fi
elif docker ps -a --format '{{.Names}}' | grep -q "^${VLLM_CONTAINER_NAME}$"; then
    echo "  Removing stopped vLLM container..."
    docker rm -f "$VLLM_CONTAINER_NAME" &>/dev/null
fi

if [ "$VLLM_RUNNING" = false ]; then
    echo ""
    echo "=============================================="
    echo "  Starting vLLM ($VLLM_MODEL)"
    echo "=============================================="
    echo ""
    echo "  This takes 5-10 minutes (model loading + CUDA compilation)"
    echo "  TIP: Leave vLLM running between sessions to skip this wait."
    echo "       Just Ctrl+C the web app, not the vLLM container."
    echo ""

    docker run -d \
        --gpus all \
        --name "$VLLM_CONTAINER_NAME" \
        --restart unless-stopped \
        -v "$HF_CACHE:/root/.cache/huggingface" \
        -p "${VLLM_PORT}:8000" \
        --ipc=host \
        "$VLLM_IMAGE" \
        --model "$VLLM_MODEL" \
        --max-model-len 32768 \
        --language-model-only \
        --default-chat-template-kwargs '{"enable_thinking": false}' \
        --max-cudagraph-capture-size 256 \
        --enable-prefix-caching \
        --kv-cache-dtype fp8_e4m3 \
        > /dev/null

    echo "  vLLM container started. Waiting for model to load..."
    echo ""

    # Wait for vLLM to become healthy
    ATTEMPTS=0
    MAX_ATTEMPTS=120
    while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
        if curl -sf "http://localhost:${VLLM_PORT}/health" &>/dev/null; then
            echo ""
            echo "  [OK] vLLM is ready!"
            break
        fi

        ATTEMPTS=$((ATTEMPTS + 1))
        ELAPSED=$((ATTEMPTS * 5))

        # Show progress every 30 seconds
        if [ $((ATTEMPTS % 6)) -eq 0 ]; then
            echo "  Still loading... (${ELAPSED}s elapsed)"
        fi

        # Check if container crashed
        if ! docker ps --format '{{.Names}}' | grep -q "^${VLLM_CONTAINER_NAME}$"; then
            echo ""
            echo "  [FAIL] vLLM container exited unexpectedly."
            echo "         Check logs with: docker logs $VLLM_CONTAINER_NAME"
            echo ""
            exit 1
        fi

        sleep 5
    done

    if [ $ATTEMPTS -ge $MAX_ATTEMPTS ]; then
        echo ""
        echo "  [FAIL] vLLM did not become healthy after 10 minutes."
        echo "         Check logs with: docker logs $VLLM_CONTAINER_NAME"
        echo ""
        exit 1
    fi
fi

# ── Detect host LAN IP ──────────────────────────────────────────────────────

if [ -z "$HOST_IP" ]; then
    HOST_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
fi
if [ -z "$HOST_IP" ]; then
    HOST_IP=$(hostname -I | awk '{print $1}')
fi
if [ -z "$HOST_IP" ]; then
    HOST_IP="localhost"
fi

# ── Start the web app ───────────────────────────────────────────────────────

cd "$SCRIPT_DIR"
python3 server.py &
APP_PID=$!

# Wait for the web app to become ready
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${APP_PORT}/api/health" &>/dev/null; then
        break
    fi
    sleep 1
done

echo ""
echo "=============================================="
echo "  HP Deck Factory"
echo "=============================================="
echo ""
echo "  Open in your browser:"
echo ""
echo "    http://${HOST_IP}:${APP_PORT}"
echo ""
echo "  vLLM:  http://${HOST_IP}:${VLLM_PORT}/health"
echo "  App:   http://${HOST_IP}:${APP_PORT}/api/health"
echo ""
echo "  Press Ctrl+C to stop the application."
echo "  To also stop vLLM: docker kill $VLLM_CONTAINER_NAME"
echo ""
echo "=============================================="
echo ""

# Handle Ctrl+C gracefully
trap "echo ''; echo '  Stopping web app...'; kill $APP_PID 2>/dev/null; exit 0" INT TERM

# Keep the script alive until the server exits
wait $APP_PID
