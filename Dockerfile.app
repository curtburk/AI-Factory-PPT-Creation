FROM node:20-slim AS node-deps
WORKDIR /app
COPY package.json ./
RUN npm install --production

FROM python:3.12-slim
WORKDIR /app

# Install Node.js runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Node dependencies
COPY --from=node-deps /app/node_modules /app/node_modules

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY server.py schemas.py prompts.py render_deck.js brand.json package.json ./
COPY templates/ templates/

# Create directories
RUN mkdir -p output logs logos

EXPOSE 8888
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8888", "--log-level", "info"]
