from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from config.constant import ROUTER_SYSTEM_PROMPT, ROUTER_VALID_ROUTES
from src.agents.base import agent_factory_model

logger = logging.getLogger(__name__)

# Heuristic fallback (used when the LLM router is unavailable or ambiguous).
# Pandas requires BOTH a campaign signal AND a freshness signal.
CAMPAIGN_TERMS = (
    "campaign",
    "marketing",
    "impression",
    "click",
    "ctr",
    "conversion",
    "revenue_generated",
    "campaign_cost",
    "profit",
    "roi",
    "channel",
)

FRESHNESS_TERMS = (
    "latest",
    "last 7",
    "last seven",
    "past 7",
    "past week",
    "this week",
    "recent",
    "current",
    "active",
    "today",
    "yesterday",
    "fresh",
    "real-time",
    "real time",
    "newest",
    "ongoing",
    "now",
)


def _contains_term(question_lower: str, term: str) -> bool:
    """Word-boundary match (allows plural/suffix, avoids 'now' in 'know')."""
    return re.search(r"\b" + re.escape(term) + r"\w*\b", question_lower) is not None


def fallback_route(question: str) -> str:
    """Deterministic keyword fallback: primary is sql, pandas only for latest campaigns."""
    q = (question or "").lower()
    has_campaign = any(_contains_term(q, term) for term in CAMPAIGN_TERMS)
    has_freshness = any(_contains_term(q, term) for term in FRESHNESS_TERMS)
    if has_campaign and has_freshness:
        return "pandas"
    return "sql"


def parse_route(text: str | None) -> str | None:
    """Parse raw LLM output into 'sql' or 'pandas'. Returns None if ambiguous."""
    if not text:
        return None
    lowered = text.strip().lower()
    match = re.search(r"\b(sql|pandas|etl)\b", lowered)
    if not match:
        return None
    token = match.group(1)
    if token == "etl":
        return "pandas"
    return token


def router_agent(question: str) -> str:
    """LLM router call, developed the same way as analyzer_agent.

    Args:
        question: the user's natural-language question.

    Returns:
        Raw LLM response text (expected to be 'sql' or 'pandas').
    """
    agent = agent_factory_model("low")
    result = agent.invoke(
        [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(
                content=f"Question: {question}\nRoute to 'sql' or 'pandas'. Reply with one word only."
            ),
        ]
    )
    return result.content


def decide_route(question: str) -> str:
    """Decide 'sql' or 'pandas' via the LLM router with deterministic fallback.

    Primary is sql. Returns 'pandas' only for latest-campaign questions.
    Never raises: falls back to keyword heuristics on LLM failure.
    """
    try:
        raw = router_agent(question)
        parsed = parse_route(raw)
        if parsed in ROUTER_VALID_ROUTES:
            return parsed
        logger.warning("Ambiguous router output %r, falling back to heuristics", raw)
    except Exception:
        logger.exception("Router agent failed, falling back to heuristics")
    return fallback_route(question)
