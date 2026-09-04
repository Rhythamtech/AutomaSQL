import os
import httpx
import pandas as pd
from base import agent_factory_model
from langchain.agents import create_agent
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv

load_dotenv()

DATA_URL = os.getenv("ETL_ENDPOINT_URL")
CSV_FILE = Path(os.getenv("ETL_CACHE_DIR", "data/etl_cache"))
MODEL =  agent_factory_model("medium")


class ETLState(TypedDict, total=False):
    data: list[dict]
    transformed_data: list[dict]
    count: int
    status: str

@tool
def fetch_data(state: ETLState) -> ETLState:
    """Fetch campaign data from the API."""
    response = httpx.get(DATA_URL, timeout=30)
    response.raise_for_status()

    payload = response.json()

    campaigns = payload.get("campaigns", [])

    return {
        "data": campaigns,
        "count": len(campaigns),
        "status": "fetched",
    }


@tool
def transform_data(state: ETLState) -> ETLState:
    """Transform campaign data."""
    records = state["data"]

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

    return {
        "transformed_data": transformed,
        "status": "transformed",
    }

@tool
def save_to_csv(state: ETLState) -> ETLState:
    """Save transformed campaign data to a local CSV file."""

    
    csv_file = CSV_FILE / "campaigns.csv"

    CSV_FILE.mkdir(
        parents=True,
        exist_ok=True,
    )

    transformed_data = state.get("transformed_data", [])

    if not transformed_data:
        return {
            "status": "skipped",
        }

    new_df = pd.DataFrame(transformed_data)

    if csv_file.exists():
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

    return {
        "status": "saved",
    }

gent = create_agent(
    model=MODEL,
    tools=[
        fetch_data,
        transform_data,
        save_to_csv,
    ],
    system_prompt="""
You are a campaign ETL agent.

Your job is to execute the campaign ETL pipeline.

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
""",
)


def build_graph():
    graph = StateGraph(ETLState)

    graph.add_node("fetch", fetch_data)
    graph.add_node("transform", transform_data)
    graph.add_node("save", save_to_csv)

    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "transform")
    graph.add_edge("transform", "save")
    graph.add_edge("save", END)

    return graph.compile()


if __name__ == "__main__":
    pipeline = build_graph()

    result = pipeline.invoke({})

    print(f"Status: {result['status']}")
    print(f"Records fetched: {result['count']}")
    print(f"CSV saved to: {CSV_FILE}")