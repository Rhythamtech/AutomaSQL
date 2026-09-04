import logging
import os
import httpx
from datetime import datetime, timezone
import pandas as pd
from base import agent_factory_model
from langgraph.graph import StateGraph, START, END
from langchain.agents import create_agent
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CURRENT_DATE = datetime.now(timezone.utc).date()
DATA_URL = os.getenv("ETL_ENDPOINT_URL")
CSV_FILE = Path(os.getenv("ETL_CACHE_DIR", "data/etl_cache"))
ETL_ARCHITECT_SYSTEM_PROMPT = """You are a campaign ETL agent.
Your job is to execute the campaign ETL pipeline. Check
Always follow this order:
1. Fetch campaign data.
2. Inspect the fetched result.
3. Transform the campaign data.
4. Save the transformed data to CSV.
5. Report what happened.
Do not skip ETL steps.
Do not invent campaign data.
If fetching fails, do not continue.
If transformation fails, do not save.
After completion, provide:
- records fetched
- records transformed
- records saved
- output CSV path
- any errors
"""


class ETLState(TypedDict, total=False):
    data: list[dict]
    transformed_data: list[dict]

    question: str
    query_result: list[dict]

    is_fresh: bool
    force_refresh: bool

    answer: str
    status: str
    error: str | None
    
    
    
from datetime import datetime, timezone
from pathlib import Path


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

    modified_at = datetime.fromtimestamp( csv_file.stat().st_mtime, tz=timezone.utc,)
    age = datetime.now(timezone.utc) - modified_at

    is_fresh = age.total_seconds() < 24 * 60 * 60

    return {
        "is_fresh": is_fresh,
        "status": "fresh" if is_fresh else "stale",
    }


def fetch_data(state: ETLState) -> ETLState:
    """Fetch campaign data from the API."""
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
    """Transform campaign data."""
    records = state["data"]
    logger.info("Transforming %d campaign records", len(records))

    try:
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
    except Exception:
        logger.exception("Failed to transform campaign data")
        raise

def save_to_csv(state: ETLState) -> ETLState:
    """Save transformed campaign data to a local CSV file."""
    csv_file = CSV_FILE / f"campaigns.csv"
    logger.info("Saving transformed data to %s", csv_file)

    CSV_FILE.mkdir(
        parents=True,
        exist_ok=True,
    )

    transformed_data = state.get("transformed_data", [])

    if not transformed_data:
        logger.warning("No transformed data to save, skipping CSV write")
        return {
            "status": "skipped",
        }

    try:
        new_df = pd.DataFrame(transformed_data)

        if csv_file.exists():
            logger.info("Existing CSV found, merging and deduping on campaign_id")
            old_df = pd.read_csv(csv_file)

            df = pd.concat(
                [old_df, new_df],
                ignore_index=True,
            )

            # campaign_id acts as the unique key.
            df = df.drop_duplicates(
                subset=["campaign_id"],
                keep="last",
            )
        else:
            df = new_df

        df.to_csv(
            csv_file,
            index=False,
        )

        logger.info("Saved %d records to %s", len(df), csv_file)
        return {
            "status": "saved",
        }
    except Exception:
        logger.exception("Failed to save CSV to %s", csv_file)
        raise
    
def query_campaigns(state: ETLState) -> ETLState:
    question = state["question"]
    csv_file = CSV_FILE / "campaigns.csv"

    df = pd.read_csv(csv_file)

    # TODO: Add logic

    # return {
    #     "query_result": df.to_dict(orient="records"),
    #     "status": "queried",
    # }
    pass


def answer(state: ETLState) -> ETLState:
    pass


def route_after_freshness(state: ETLState) -> str:
    if state.get("is_fresh", False):
        return "query"

    return "fetch"


def build_etl_graph():
    graph = StateGraph(ETLState)

    graph.add_node("check_freshness", check_data_freshness)
    graph.add_node("fetch", fetch_data)
    graph.add_node("transform", transform_data)
    graph.add_node("save", save_to_csv)
    graph.add_node("query", query_campaigns)
    graph.add_node("answer", answer)

    graph.add_edge(START, "check_freshness")

    graph.add_conditional_edges(
        "check_freshness",
        route_after_freshness,
        {
            "query": "query",
            "fetch": "fetch",
        },
    )

    graph.add_edge("fetch", "transform")
    graph.add_edge("transform", "save")
    graph.add_edge("save", "query")
    graph.add_edge("query", "answer")
    graph.add_edge("answer", END)

    return graph.compile()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    logger.info("Starting campaign ETL workflow")

    graph = build_etl_graph()

    result = graph.invoke(
        {
            "question": "Which campaign generated the most revenue?",
            "force_refresh": False,
        }
    )

    answer = result.get("answer")

    if answer:
        print(answer)
    else:
        logger.warning("Workflow completed without an answer")
