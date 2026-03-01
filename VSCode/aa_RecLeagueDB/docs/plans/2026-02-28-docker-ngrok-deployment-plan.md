# Docker + ngrok Deployment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add RecSportsDB Streamlit app as a Docker service in n8n-docker, exposed at `recsportsdb.ngrok.app` with basic auth.

**Architecture:** `Dockerfile` + `requirements-streamlit.txt` live in `aa_RecLeagueDB/`. Two new services (`recsports` + `ngrok_recsports`) are appended to `n8n-docker/docker-compose.yml`. Code is bind-mounted so changes auto-reload without rebuilds. App keys come from `aa_RecLeagueDB/.env`; the ngrok authtoken comes from `n8n-docker/.env`.

**Tech Stack:** Docker, docker-compose, python:3.11-slim, ngrok/ngrok:latest, Streamlit

**Basic auth credentials:** `recsports:RecSports2026` — change before running if desired.

---

## Context You Need

- **Project root:** `C:/Users/mathe/VSCode/aa_RecLeagueDB/`
- **Compose file:** `C:/Users/mathe/n8n-docker/docker-compose.yml`
- **n8n .env:** `C:/Users/mathe/n8n-docker/.env` — add `NGROK_AUTHTOKEN_RECSPORTS` here
- **App .env:** `C:/Users/mathe/VSCode/aa_RecLeagueDB/.env` — already has Supabase/OpenAI/Serper keys
- **ngrok domain:** `recsportsdb.ngrok.app` (already reserved on user's account)
- **Port mapping:** host `8502` → container `8501` (Streamlit default)
- **All commands run from:** `C:/Users/mathe/VSCode/aa_RecLeagueDB`

---

## Task 1: Slim Requirements + Dockerfile

**Files:**
- Create: `aa_RecLeagueDB/requirements-streamlit.txt`
- Create: `aa_RecLeagueDB/Dockerfile`

### Step 1: Create `requirements-streamlit.txt`

Keeps only what the Streamlit UI and its `src/` imports actually need.
Drops: browser automation, HTML parsers, vector store client, dev tools, test tools.

```
# requirements-streamlit.txt — UI-only deps (no browser automation)

# Core
python-dotenv>=1.0.0
requests>=2.31.0

# Database
supabase>=2.3.0

# AI/LLM (needed by SearchOrchestrator)
anthropic>=0.40.0
openai>=1.12.0
langchain>=0.1.0
langchain-openai>=0.0.5
langgraph>=0.0.20
tiktoken>=0.6.0

# Data
pandas>=2.2.0
pydantic>=2.6.0
PyYAML>=6.0

# Utilities
python-dateutil>=2.8.0
pytz>=2024.1
loguru>=0.7.0

# Web UI
streamlit>=1.31.0
```

### Step 2: Create `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements-streamlit.txt .
RUN pip install --no-cache-dir -r requirements-streamlit.txt

EXPOSE 8501

CMD ["streamlit", "run", "streamlit_app/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
```

### Step 3: Verify build (no containers started yet)

```bash
cd "C:/Users/mathe/VSCode/aa_RecLeagueDB"
docker build -t recsports-test .
```

Expected: `Successfully built <id>` — no errors.
If pip install fails on a package, remove it from `requirements-streamlit.txt` (it may not be needed by the UI).

### Step 4: Commit

```bash
git add requirements-streamlit.txt Dockerfile
git commit -m "feat: add slim Dockerfile for Streamlit UI deployment"
```

---

## Task 2: Add Services to docker-compose.yml

**Files:**
- Modify: `n8n-docker/docker-compose.yml`

### Step 1: Add `NGROK_AUTHTOKEN_RECSPORTS` to `n8n-docker/.env`

Open `C:/Users/mathe/n8n-docker/.env` and add this line (use the authtoken created for RecSports):

```
NGROK_AUTHTOKEN_RECSPORTS=<paste your recsports authtoken here>
```

### Step 2: Add two services to `docker-compose.yml`

Open `C:/Users/mathe/n8n-docker/docker-compose.yml`.

**Find this block** (just before `volumes:`):
```yaml
volumes:
  postgres_data:
  n8n_data:
```

**Insert these two services immediately above it:**
```yaml
  # RecSportsDB Streamlit app — bind-mounted, port 8502 on host
  recsports:
    build: ../VSCode/aa_RecLeagueDB
    restart: unless-stopped
    ports:
      - "8502:8501"
    volumes:
      - ../VSCode/aa_RecLeagueDB:/app
    env_file:
      - ../VSCode/aa_RecLeagueDB/.env
    networks: [n8nnet]

  # ngrok for RecSports — fixed domain, WITH basic auth
  ngrok_recsports:
    image: ngrok/ngrok:latest
    restart: unless-stopped
    depends_on:
      - recsports
    command: >
      http
      --log=stdout
      --domain=recsportsdb.ngrok.app
      --basic-auth=recsports:RecSports2026
      http://host.docker.internal:8502
    environment:
      NGROK_AUTHTOKEN: ${NGROK_AUTHTOKEN_RECSPORTS}
    ports:
      - "4042:4040"   # Inspector -> http://localhost:4042/status
    networks: [n8nnet]

```

### Step 3: Validate compose file

```bash
cd "C:/Users/mathe/n8n-docker"
docker compose config --quiet
```

Expected: no output (quiet means valid). Any YAML errors will be printed.

### Step 4: Start the new services

```bash
docker compose up -d recsports ngrok_recsports
```

This starts only the two new services without restarting n8n/postgres.

### Step 5: Verify services are running

```bash
docker compose ps recsports ngrok_recsports
```

Expected: both show `running`.

Check Streamlit is up on the host:
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8502
```
Expected: `200`

Check ngrok tunnel is active:
```
Open http://localhost:4042/status in browser
```
Expected: tunnel shows `recsportsdb.ngrok.app` as online.

### Step 6: Commit

```bash
cd "C:/Users/mathe/VSCode/aa_RecLeagueDB"
git add ../../../n8n-docker/docker-compose.yml
git commit -m "feat: add recsports + ngrok_recsports services to docker-compose"
```

Note: if the n8n-docker directory is outside this git repo, commit from `C:/Users/mathe` instead:
```bash
cd "C:/Users/mathe"
git add n8n-docker/docker-compose.yml
git commit -m "feat: add recsports + ngrok_recsports services to docker-compose"
```

---

## Final Check

Visit `https://recsportsdb.ngrok.app` in a browser.
- Browser prompts for basic auth → enter `recsports` / `RecSports2026`
- RecSportsDB Queue Monitor and other pages load correctly
- Stats bar shows counts, filters work

Done.
