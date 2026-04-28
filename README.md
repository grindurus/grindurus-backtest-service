# Backtest service

HTTP API for the Grindurus backtest **queue** and **history**: clients submit backtest jobs, workers poll the queue and report status, and completed runs can be recorded in history. Built with **FastAPI**, **SQLAlchemy 2 (async)**, and **PostgreSQL**.

Interactive docs: `GET /docs` (Swagger UI) when the API is running.

## What it exposes

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/backtest` | Enqueue a new backtest (flat fields or legacy `params` + `owner_address`) |
| `GET` | `/queue` | List queue items (`limit`, optional `status`) |
| `POST` | `/queue/next` | Pop the next pending job (priority + FIFO) |
| `PATCH` | `/queue/{queue_id}/status` | Update job status (`pending`, `processing`, `done`, `failed`) |
| `POST` | `/history` | Append a completed backtest to history |
| `GET` | `/history` | List history (`limit`) |
| `GET` | `/health` | Liveness check |

On startup the app ensures the database schema exists (including lightweight compatibility migrations for older column layouts).

## Requirements

- **Python** ≥ 3.13.7 (matches the Docker image)
- **PostgreSQL** 16+ (async URL must use the `postgresql+asyncpg://` scheme)

## Configuration

Environment variables (optional `.env`; see `db/settings.py`):

| Variable | Default (dev) | Notes |
|----------|----------------|--------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/backtests` | Must match your Postgres user, password, host, and database |
| `APP_MODE` | `dev` | Informational; compose sets `dev` / `prod` |
| `PAYMENT_WALLET_ADDRESS` | `0x...` from settings | Receiver wallet for x402 payments |
| `BACKTEST_PRICE` | `$1.00` | x402 price for `POST /backtest` (must include `$`; auto-normalized if omitted) |
| `X402_FACILITATOR_URL` | `https://x402.org/facilitator` | x402 facilitator URL (use CDP URL for production) |
| `X402_NETWORK` | `eip155:84532` | x402 CAIP-2 network id (Base Sepolia by default) |

## Run without Docker

1. Create a database and set `DATABASE_URL`.
2. Install: `pip install -e ".[dev]"` (from this directory).
3. Start API: `python main.py` or `uvicorn main:app --host 0.0.0.0 --port 8001 --reload`.

The API listens on **port 8001** by default.

---

## Docker

Two Compose files are provided.

### Development (`docker-compose.dev.yml`)

Runs Postgres + API with **hot reload** and **port 8001** published to the host.

```bash
cd grindurus-backtest-service
docker compose -f docker-compose.dev.yml up -d --build
```

- **API:** http://localhost:8001  
- **Docs:** http://localhost:8001/docs  
- **Postgres:** `localhost:5432`, user `backtest`, password `backtest`, database `backtest`

Stop and remove containers (volumes are kept unless you add `-v`):

```bash
docker compose -f docker-compose.dev.yml down
```

Logs:

```bash
docker compose -f docker-compose.dev.yml logs -f api
```

If something else already uses host port **5432**, change the `db` service `ports` mapping in `docker-compose.dev.yml` or stop the conflicting service.

### Production-style stack (`docker-compose.yml`)

Builds the same image but runs the API **without** publishing `8001` on the host. It expects **Traefik** (or similar) on the Docker network **`grindurus`**, with routes for:

- `backtest.localhost` (HTTP, local)
- `backtest.grindurus.xyz` (HTTP → HTTPS redirect + TLS)

Bring the stack up:

```bash
cd grindurus-backtest-service
docker compose up -d --build
```

Ensure your Traefik stack defines the external network `grindurus` and attach this project’s services to it if labels require that network (you may need to add a `networks:` block to match your infrastructure).

Postgres is still exposed on the host as **5432** in this file; tighten or remove that in real production if the database should not be reachable from the host.

---

## Project layout

- `main.py` — FastAPI app and routes  
- `db/` — models, async session, schemas, queue/history service, settings  
- `boss/` — HTTP client utilities for external services  
- `dockerfile` — Python 3.13 slim image, installs the package, default command runs `main.py` on port **8001**
