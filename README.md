# HP Deck Factory

An AI-powered PowerPoint generator that runs entirely on-premises. Describe your presentation in plain English, pick your brand colors, upload your logo, and download a polished `.pptx` file. No cloud APIs. No data leaves the building.

**Powered by:** HP ZGX Nano AI Station, Qwen3.6-27B-FP8, vLLM

---

## What It Does

1. You type a description of the presentation you want (e.g., "Create a pitch deck about AI in healthcare for our sales team")
2. You optionally provide a specific deck title, brand colors, and a logo
3. AI generates a structured slide plan with varied layouts (title slides, bullet points, charts, stat callouts, icon grids, comparison columns, and more)
4. A deterministic renderer converts the plan into a real `.pptx` PowerPoint file
5. You download the file and open it in PowerPoint, Google Slides, or Keynote

**Key features:**
- 9 professional slide layouts (title, bullets, two-column, stat callout, chart, icon grid, image+text, section divider, closing)
- Custom brand colors (background, text, highlight) applied to every slide
- Logo placement on every slide (bottom-right corner, aspect ratio preserved)
- Conversation memory -- refine your deck iteratively ("change slide 3 to a chart", "make the bullets more specific")
- Structured JSON output via vLLM's constrained decoding guarantees valid output every time

---

## Prerequisites

Before starting, make sure the following are installed on the HP ZGX Nano:

| Requirement | How to check | Install if missing |
|---|---|---|
| Python 3.10+ | `python3 --version` | Should be pre-installed |
| Node.js 20+ | `node --version` | `curl -fsSL https://deb.nodesource.com/setup_20.x \| sudo bash - && sudo apt install nodejs` |
| Docker | `docker --version` | Should be pre-installed |
| NVIDIA GPU drivers | `nvidia-smi` | Should be pre-installed |
| Git | `git --version` | `sudo apt install git` |

---

## Setup Instructions

### Step 1: Clone the repository

```bash
cd ~/Desktop
git clone https://github.com/curtburk/AI-Factory-PPT-Creation.git
cd AI-Factory-PPT-Creation
```

### Step 2: Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Install Node.js dependencies

```bash
npm install
```

### Step 4: Start the application

```bash
./start.sh
**Note: The model (~28 GB) will be downloaded automatically the first time vLLM starts. Make sure you have enough disk space and this adds a few minutes to first startup**
```

The startup script handles everything automatically:

1. Checks that Docker, GPU, Node.js, and Python are available
2. Installs any missing dependencies
3. Starts the AI engine (vLLM) if it isn't already running
4. Waits for the model to finish loading
5. Launches the web application
6. Prints the URL to open in your browser

**First startup takes 5-10 minutes** because the AI model (28 GB) needs to load into GPU memory and compile optimized kernels. You'll see progress updates in the terminal.

**Every subsequent startup is instant** because the script detects that the AI engine is already running and skips straight to launching the web app.

### Step 6: Open in your browser

When the startup finishes, you'll see a URL in the terminal. Open it in your browser:

**http://192.xxx.xx.xxx:8888**

(The actual IP of your machine will print with the clickable link)

---

## How to Use

### Creating a deck

1. **Describe your deck** in the text area. The more specific you are, the better the output. A rough outline works best, for example:

   ```
   Create a 6-slide deck for our sales team about AI in healthcare.
   1. Title slide 
   2. The market opportunity
   3. Why HP is uniquely positioned
   4. A use case of AI in healthcare
   5. A wrap up with key call to action
   6. Thank you slide
   ```

2. **Set the deck title** (optional) in the "Deck Title" field. Whatever you type here will appear exactly as written on the title slide.

3. **Pick brand colors** (optional). Click the color swatches or type hex codes directly:
   - **Background** -- slide background color
   - **Text** -- heading and body text color
   - **Highlight** -- accent color for stats, icons, charts, and decorative elements

4. **Upload a logo** (optional). Click the logo area and select a PNG, JPG, or SVG file. The logo will appear in the bottom-right corner of every slide.

5. Click **Generate Deck** and wait. Generation typically takes 60-120 seconds.

6. Click **Download .pptx** to save the file.

### Refining a deck

After generating a deck, you can make changes without starting over:

1. Type your change in the refinement text area below the download button (e.g., "Change slide 3 to a chart showing quarterly revenue" or "Make the bullet points more specific")
2. Click **Refine Deck**
3. Download the updated version

The AI remembers the previous conversation, so you don't need to re-explain the whole deck.

### Starting over

Click **Start Over** to clear everything and begin a new deck.

---

## Adding Your Logo to the Header

To display your company logo next to "Deck Factory" in the web app header:

1. Copy your logo file to the `logos/` directory and name it `header_logo.png`:

```bash
cp your_logo.png logos/header_logo.png
```

2. Refresh the browser

---

## Troubleshooting

### "vLLM not available" error

The AI engine isn't running or hasn't finished loading. Check the vLLM terminal for errors. Wait for the "Uvicorn running" message before using the app.

### Generation takes a very long time (>3 minutes)

The first request after starting vLLM is slower due to CUDA graph warmup. Subsequent requests should be faster. If it's consistently slow, check `nvidia-smi` to make sure the GPU isn't being used by another process.

### Logo looks wrong on slides

Use a PNG with a transparent background for best results. Logos with solid backgrounds (especially black or white) will show the background on the slide.

### Colors don't seem right

Make sure the background color has enough contrast with the text color. White text on a white background will be invisible (the renderer handles this automatically for title and closing slides, but other slides may not adapt).

### "Validation error" in the logs

The AI model produced output that didn't match the expected format. This is rare with constrained decoding but can happen. Try generating again -- each generation is independent.

### Port 8000 or 8888 already in use

Find and stop the process using the port:

```bash
# Find what's using port 8000
lsof -i :8000

# Or kill all Docker containers
docker kill $(docker ps -q)
```

---

## File Structure

```
PPT-deck-factory/
  start.sh                -- Startup script (run this!)
  server.py               -- Web application (FastAPI)
  schemas.py             -- JSON schema for deck plans (Pydantic models)
  prompts.py             -- AI system prompt
  render_deck.js         -- PowerPoint renderer (Node.js, pptxgenjs)
  brand.json             -- Runtime color config (auto-generated)
  requirements.txt       -- Python dependencies
  package.json           -- Node.js dependencies
  docker-compose.yml     -- Docker Compose config (alternative startup)
  Dockerfile.app         -- Docker build for the web app
  templates/
    index.html           -- Web frontend
  logos/
    header_logo.png      -- Logo in the web app header
    current_logo.png     -- Logo uploaded for slides (auto-generated)
  output/                -- Generated .pptx files (auto-generated)
  logs/                  -- Application logs (auto-generated)
```

---

## Stopping the Application

### Stopping the web app (recommended between sessions)

Press `Ctrl+C` in the terminal where `start.sh` is running. This stops the web app only. The AI engine (vLLM) keeps running in the background so your next `./start.sh` is instant.

### Stopping the AI engine (only if you need GPU resources for other work)

> **Important:** The AI engine takes 5-10 minutes to restart. Only stop it if you need to free up GPU memory for other work (e.g., running a different demo, training a model, or using the GPU for another application). Under normal use, leave it running.

```bash
docker kill deck-factory-vllm
docker rm deck-factory-vllm
```

To check if the AI engine is currently running:

```bash
docker ps | grep deck-factory-vllm
```

---

## Alternative: Docker Compose Startup

If you prefer to start everything with one command:

```bash
docker compose up
```

This starts both vLLM and the web app. Note: the web app container needs Node.js and Python, so the first build takes a few minutes.

To stop:

```bash
docker compose down
```
