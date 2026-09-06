import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

from src.agents.execution_sandbox import analyzer_agent, execute_safe
from src.agents.pandas_engineer import engineer as pandas_engineer
from src.graph.state import ETLState

load_dotenv()

logger = logging.getLogger(__name__)

DATA_URL = os.getenv("ETL_ENDPOINT_URL")
CSV_FILE = Path(os.getenv("ETL_CACHE_DIR", "data/etl_cache"))


def check_data_freshness(state: ETLState) -> ETLState:
    csv_file = CSV_FILE / "campaigns.csv"
    force_refresh = state.get("force_refresh", False)

    if force_refresh:
        return {
            "is_fresh": False,
            "status": "refresh_required",
        }

    if not csv_file.exists():
        return {
            "is_fresh": False,
            "status": "data_missing",
        }

    modified_at = datetime.fromtimestamp(
        csv_file.stat().st_mtime,
        tz=timezone.utc,
    )
    age = datetime.now(timezone.utc) - modified_at
    is_fresh = age.total_seconds() < 24 * 60 * 60

    return {
        "is_fresh": is_fresh,
        "status": "fresh" if is_fresh else "stale",
    }


def fetch_data(state: ETLState) -> ETLState:
    logger.info("Fetching campaign data from %s", DATA_URL)
    try:
        response = httpx.get(DATA_URL, timeout=30)
        response.raise_for_status()
        payload = response.json()
        campaigns = payload.get("campaigns", [])

        logger.info("Fetched %d campaigns", len(campaigns))
        return {
            "data": campaigns,
            "count": len(campaigns),
            "status": "fetched",
        }
    except Exception:
        logger.exception("Failed to fetch campaign data")
        raise


def transform_data(state: ETLState) -> ETLState:
    records = state["data"]
    logger.info("Transforming %d campaign records", len(records))

    transformed = []
    for campaign in records:
        impressions = campaign.get("impressions", 0)
        clicks = campaign.get("clicks", 0)
        conversions = campaign.get("conversions", 0)
        cost = campaign.get("campaign_cost", 0)
        revenue = campaign.get("revenue_generated", 0)

        ctr = clicks / impressions if impressions else 0
        conversion_rate = conversions / clicks if clicks else 0
        profit = revenue - cost

        transformed.append(
            {
                **campaign,
                "ctr": round(ctr, 4),
                "conversion_rate": round(conversion_rate, 4),
                "profit": round(profit, 2),
            }
        )

    logger.info("Transformed %d records", len(transformed))
    return {
        "transformed_data": transformed,
        "status": "transformed",
    }


def save_to_csv(state: ETLState) -> ETLState:
    csv_file = CSV_FILE / "campaigns.csv"
    logger.info("Saving transformed data to %s", csv_file)

    CSV_FILE.mkdir(parents=True, exist_ok=True)
    transformed_data = state.get("transformed_data", [])

    if not transformed_data:
        logger.warning("No transformed data to save, skipping CSV write")
        return {"status": "skipped"}

    new_df = pd.DataFrame(transformed_data)

    if csv_file.exists():
        old_df = pd.read_csv(csv_file)
        df = pd.concat([old_df, new_df], ignore_index=True)
        df = df.drop_duplicates(subset=["campaign_id"], keep="last")
    else:
        df = new_df

    df.to_csv(csv_file, index=False)
    logger.info("Saved %d records to %s", len(df), csv_file)
    return {
        "status": "saved",
        "count": len(df),
    }


def query_campaigns(state: ETLState) -> ETLState:
    question = state["question"]
    df = pd.read_csv(CSV_FILE / "campaigns.csv")
    expression = pandas_engineer(question)

    if expression.get("status") != "SUCCESS":
        return {
            "status": "query_failed",
            "error": expression.get("error", "Could not create a valid query."),
        }

    result = execute_safe(expression["expression"], df)
    return {
        "query_result": result,
        "status": "queried",
    }


def answer(state: ETLState) -> ETLState:
    question = state["question"]
    result = state.get("query_result")

    if result is None or (hasattr(result, "empty") and result.empty):
        return {
            "answer": "Sorry, I couldn't answer your question. Please try again later.",
            "status": "answer_failed",
        }

    return {
        "answer": analyzer_agent(question, result),
        "status": "answered",
    }


def route_after_freshness(state: ETLState) -> str:
    if state.get("is_fresh", False):
        return "query"

    return "fetch"
