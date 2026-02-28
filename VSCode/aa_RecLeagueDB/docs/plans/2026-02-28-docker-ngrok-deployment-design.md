# Docker + ngrok Deployment Design

**Date:** 2026-02-28
**Goal:** Run RecSportsDB Streamlit app as a Docker service alongside the existing n8n stack, exposed via ngrok with basic auth.

---

## Architecture

Two new services added to `n8n-docker/docker-compose.yml`:

- **`recsports`** — Streamlit container (port 8502 on host, 8501 in container). Code bind-mounted from `../VSCode/aa_RecLeagueDB`. App keys loaded via `env_file` from `aa_RecLeagueDB/.env`.
- **`ngrok_recsports`** — Tunnels `host.docker.internal:8502` → `recsportsdb.ngrok.app` with basic auth. Inspector on `localhost:4042`. Uses `NGROK_AUTHTOKEN_RECSPORTS` from `n8n-docker/.env`.

## Files

| File | Action |
|------|--------|
| `aa_RecLeagueDB/requirements-streamlit.txt` | Create — slim deps (no browser automation, no dev tools) |
| `aa_RecLeagueDB/Dockerfile` | Create — python:3.11-slim, installs slim deps, bind-mount entry |
| `n8n-docker/docker-compose.yml` | Modify — add `recsports` + `ngrok_recsports` services |
| `n8n-docker/.env` | User adds `NGROK_AUTHTOKEN_RECSPORTS=<token>` manually |

## Env Var Split

- `n8n-docker/.env` → ngrok tokens only
- `aa_RecLeagueDB/.env` → Supabase, OpenAI, Serper, Firecrawl keys

## ngrok Config

- Domain: `recsportsdb.ngrok.app`
- Basic auth: yes (credentials TBD by user)
- Inspector: `localhost:4042`

## Slim Dependencies (excluded from requirements-streamlit.txt)

Excluded: `selenium`, `undetected-chromedriver`, `playwright`, `webdriver-manager`, `firecrawl-py`, `pgvector`, `numpy`, `lxml`, `beautifulsoup4`, `mcp`, `black`, `flake8`, `mypy`, `pytest`, `pytest-asyncio`, `pytest-mock`
