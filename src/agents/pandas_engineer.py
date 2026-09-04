import logging
from typing import Any
from pathlib import Path
import pandas as pd
from langchain.agents import create_agent
from langchain_core.tools import tool
from base import agent_factory_model

logger = logging.getLogger(__name__)


PANDAS_ENGINEER_SYSTEM_PROMPT = """
You are a Pandas data analysis engineer.

Your job is to answer natural-language questions about a campaign.
And task is to write a valid string expression to be passed inside a pandas df.query() function.
Return ONLY the raw string expression inside the query.
Do not include markdown code blocks, backticks, or explanations.

Rules:
- Always use the query_campaigns tool to retrieve data.
- Never invent values.
- Use only columns available in the DataFrame.
"""


CSV_FILE = Path("data/etl_cache/campaigns.csv")


def get_data_context(max_rows: int = 5) -> str:
    """Return first `max_rows` of the campaign CSV as markdown with header."""
    try:
        if not CSV_FILE.exists():
            return "No cached campaign data available."
        df = pd.read_csv(CSV_FILE, nrows=max_rows)
        if df.empty:
            return "Campaign cache is empty."
        try:
            return df.to_markdown(index=False)
        except Exception:
            header = "| " + " | ".join(map(str, df.columns)) + " |"
            sep = "| " + " | ".join(["---"] * len(df.columns)) + " |"
            rows = ["| " + " | ".join(map(str, r)) + " |" for r in df.itertuples(index=False, name=None)]
            return "\n".join([header, sep, *rows])
    except Exception:
        return "Campaign preview unavailable."


# def query_campaigns(query: str) -> list[dict[str, Any]]:
#     """
#     Query campaign data from the cached CSV using Pandas.

#     The CSV is loaded fresh for every query so the tool always reads
#     the latest persisted ETL result.
#     """

#     if not CSV_FILE.exists():
#         raise FileNotFoundError(
#             f"Campaign cache does not exist: {CSV_FILE}"
#         )

#     try:
#         df = pd.read_csv(CSV_FILE)

#         if df.empty:
#             return []

#         logger.info(
#             "Loaded %d campaign records from %s",
#             len(df),
#             CSV_FILE,
#         )

#         logger.info("Executing query: %s", query)

#         result = df.query(query)

#         return result.to_dict(orient="records")

#     except pd.errors.EmptyDataError as exc:
#         raise ValueError("Campaign CSV is empty or invalid.") from exc

#     except Exception:
#         logger.exception("Failed to query campaign CSV")
#         raise


def build_pandas_engineer_agent():
    """Build the Pandas Engineer agent."""

    model = agent_factory_model("medium")

    csv_context = get_data_context(max_rows=5)
    system_prompt = (
        f"{PANDAS_ENGINEER_SYSTEM_PROMPT}\n\n"
        f"Campaign data preview (up to 5 rows):\n{csv_context}"
    )

    return create_agent(
        name="Pandas Engineer",
        model=model,
        tools=[],
        system_prompt=system_prompt,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    agent = build_pandas_engineer_agent()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Which campaign generated the most revenue?"}]}
    )
    messages = result.get("messages", [])
    if messages:
        print(messages[-1].content)
        print(query_campaigns(str(messages[-1].content)))
        
    else:
        print(result)
        
        
