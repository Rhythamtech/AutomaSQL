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
