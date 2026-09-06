# AutomaSQL

Synthetic Indian e-commerce dataset + Postgres ingest + Campaigns API.

## Setup

```bash
uv sync
cp .env.example .env  # set DATABASE_URL
```

Requires Python >=3.12.

## Dataset

Generates 9 CSVs (customers, products, orders, etc.) into `data/`:

```bash
uv run python dataset.py
```

## Ingest

Load CSVs into Postgres:

```bash
uv run python ingest.py          # truncate + load
uv run python ingest.py --drop   # drop + recreate tables
```

## API

In-memory campaigns API (no DB, no data folder):

```bash
uv run uvicorn etl_api:app --reload
```

- `GET /` — status
- `GET /health` — today
- `GET /api/campaigns` — active campaigns (`start <= today-7 AND end > today`)
- `GET /api/campaigns/{id}` — single campaign

Query params: `?channel=&type=&as_of=YYYY-MM-DD`

Docs: `http://localhost:8000/docs`

## Observability (Arize Phoenix)

Open-source LLM evaluation and observability that runs locally with no login.
Every LangGraph run (router -> SQL / ETL+pandas -> answer) and every LLM call
(router, SQL engineer, pandas engineer, analyzer, eval judges) is traced via
OpenInference auto-instrumentation.

```bash
uv sync
uv run phoenix serve          # UI at http://localhost:6006 (no login)
uv run python main.py         # traces appear under project "automasql"
uv run python evals.py        # traces + judge scores (also uploaded as dataset)
```

 knobs (see `.env.example`): `PHOENIX_ENABLED`, `PHOENIX_PROJECT_NAME`,
`PHOENIX_HOST`, `PHOENIX_PORT`, `PHOENIX_COLLECTOR_ENDPOINT`,
`PHOENIX_LAUNCH_UI`. Tracing is a safe no-op when Phoenix is not installed
or `PHOENIX_ENABLED=false`, so the app still runs without observability.
