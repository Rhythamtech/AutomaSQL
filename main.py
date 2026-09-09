"""Realistic full-workflow demo for AutomaSQL.

Runs the compiled LangGraph workflow end-to-end across multiple scenarios so
both routing branches are exercised:

- SQL (Postgres, data till T-2, PRIMARY): customers, products,
  marketing_campaign, orders, order_items, payments, shipments, returns,
  customer_reviews, including *historical* campaign analysis.
- ETL/Pandas (last 7 days campaign cache, latest campaigns only):
  campaign_start_date >= today-30 AND campaign_start_date <= today-7
  AND campaign_end_date > today. Only for questions needing data fresher
  than T-2.
Just run: python main.py (scenarios run one by one, in order).
"""
from __future__ import annotations

import logging
import time
import traceback

from src.graph.orchestrator import build_graph
from src.utils.observability import span

logger = logging.getLogger(__name__)

# Each scenario documents *why* it should take its expected route. The
# historical-vs-latest campaign contrast (scenarios 4 vs 5/6) is the key
# router behaviour: same domain, different freshness requirement.
SCENARIOS: list[dict] = [
    {
        "id": "sql-top-customers",
        "name": "SQL: top customers by order value",
        "question": "Who are our top 5 customers by total order value?",
        "force_refresh": False,
        "expected_route": "sql",
        "why": "Customers/orders live in Postgres (till T-2). No freshness signal.",
    },
    {
        "id": "sql-top-products",
        "name": "SQL: top products by revenue",
        "question": "What are the top 5 products by revenue?",
        "force_refresh": False,
        "expected_route": "sql",
        "why": "Products/order_items live in Postgres. No freshness signal.",
    },
    {
        "id": "sql-payments-returns",
        "name": "SQL: payments and returns health",
        "question": "How many payments succeeded vs failed by payment method, and what are the most common return reasons?",
        "force_refresh": False,
        "expected_route": "sql",
        "why": "Payments/returns live in Postgres (till T-2). Joins + aggregation.",
    },
    {
        "id": "sql-historical-campaigns",
        "name": "SQL: historical campaign ROI (T-2)",
        "question": "Show top 5 historical campaigns by ROI with highest revenue using database data till T-2",
        "force_refresh": False,
        "expected_route": "sql",
        "why": "Campaign question WITHOUT a latest/fresh signal stays on SQL.",
    },
    {
        "id": "etl-latest-campaigns",
        "name": "ETL: latest campaigns, last 7 days (fresh cache)",
        "question": "Show the latest campaigns by ROI in the last 7 days",
        "force_refresh": False,
        "expected_route": "pandas",
        "why": "Campaign + latest/last-7-days signal needs data fresher than T-2.",
    },
    {
        "id": "etl-active-refresh",
        "name": "ETL: active campaigns right now (forced refetch)",
        "question": "Which active campaigns are running right now? Show current CTR and profit",
        "force_refresh": True,
        "expected_route": "pandas",
        "why": "Forces fetch -> transform -> save -> query_pandas branch.",
    },
]


def _preview_result(query_result: object, limit: int = 5) -> str:
    """Render a short preview for DataFrame / list[dict] / scalar results."""
    if query_result is None:
        return "<no result>"
    # Pandas DataFrame (has .head/.shape, no import needed).
    if hasattr(query_result, "head") and hasattr(query_result, "shape"):
        try:
            shape = getattr(query_result, "shape", "?")
            head = query_result.head(limit).to_string(index=False)
            return f"rows={shape}\n{head}"
        except Exception:
            pass
    if isinstance(query_result, list):
        preview_rows = query_result[:3]
        more = f" ... (+{len(query_result) - 3} more)" if len(query_result) > 3 else ""
        return f"rows={len(query_result)} {preview_rows}{more}"
    text = str(query_result)
    return text if len(text) <= 800 else text[:800] + " ... [truncated]"


def run_scenario(graph, scenario: dict) -> dict:
    """Invoke the full graph for one scenario and print a realistic report."""
    force_refresh = scenario["force_refresh"]
    question = scenario["question"]
    print("=" * 78)
    print(f"[{scenario['id']}] {scenario['name']}")
    print(f"  Question      : {question}")
    print(f"  Expected route: {scenario['expected_route']} ({scenario['why']})")
    print(f"  force_refresh : {force_refresh}")
    print("-" * 78)

    started = time.perf_counter()
    try:
        with span(
            f"scenario.{scenario['id']}",
            {
                "automasql.scenario_id": scenario["id"],
                "automasql.question": question,
                "automasql.expected_route": scenario.get("expected_route"),
                "automasql.force_refresh": force_refresh,
            },
        ):
            result = graph.invoke({"question": question, "force_refresh": force_refresh})
    except Exception as exc:  # one bad scenario must not kill the whole run
        elapsed = time.perf_counter() - started
        # The graph raises when a downstream node (e.g. pandas_engineer LLM
        # call) throws instead of returning an error status. Routing itself
        # already succeeded at that point, so resolve it separately for an
        # honest report instead of showing "-".
        try:
            from src.agents.router import decide_route

            resolved_route = decide_route(question)
        except Exception:
            resolved_route = "-"
        route_match = resolved_route == scenario["expected_route"]
        mark = "OK " if route_match else "MISMATCH"
        print(f"  Actual route  : {resolved_route} [{mark}] (resolved before failure)")
        print(f"  EXCEPTION after {elapsed:.1f}s: {exc} (status=exception)")
        print("  Note: downstream node raised; see traceback for the failing step.")
        traceback.print_exc(limit=3)
        return {
            **scenario,
            "force_refresh": force_refresh,
            "actual_route": resolved_route,
            "route_match": route_match,
            "status": "exception",
            "error": str(exc),
            "answer": "",
            "elapsed": elapsed,
        }
    elapsed = time.perf_counter() - started

    actual_route = result.get("route", "-")
    status = result.get("status", "-")
    error = result.get("error", "")
    sql = result.get("sql", "")
    is_fresh = result.get("is_fresh", "-")
    answer = result.get("answer", "")
    route_match = actual_route == scenario["expected_route"]
    mark = "OK " if route_match else "MISMATCH"

    print(f"  Actual route  : {actual_route} [{mark}]  (status={status}, {elapsed:.1f}s)")
    if actual_route == "pandas":
        print(f"  ETL freshness : is_fresh={is_fresh}")
    if sql:
        print("  Generated SQL :")
        for line in str(sql).splitlines():
            print(f"    {line}")
    print("  Query result  :")
    for line in _preview_result(result.get("query_result")).splitlines()[:15]:
        print(f"    {line}")
    if answer:
        print("  Final answer  :")
        for line in str(answer).splitlines()[:20]:
            print(f"    {line}")
    if error and not answer:
        print(f"  Error         : {error}")
    print()
    return {
        **scenario,
        "force_refresh": force_refresh,
        "actual_route": actual_route,
        "route_match": route_match,
        "status": status,
        "error": error,
        "answer": answer,
        "elapsed": elapsed,
    }


def print_summary(outcomes: list[dict]) -> None:
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    header = f"{'#':<3} {'scenario':<32} {'exp':<7} {'got':<7} {'match':<9} {'status':<16} {'time':<7} answer"
    print(header)
    print("-" * len(header))
    for i, o in enumerate(outcomes, 1):
        answer_snippet = str(o.get("answer") or o.get("error") or "").replace("\n", " ")
        if len(answer_snippet) > 70:
            answer_snippet = answer_snippet[:70] + "..."
        print(
            f"{i:<3} {o['id']:<32} {o.get('expected_route', '-'): <7} "
            f"{o.get('actual_route', '-'): <7} "
            f"{'OK' if o.get('route_match') else 'MISMATCH':<9} "
            f"{str(o.get('status')):<16} {o.get('elapsed', 0):<7.1f} {answer_snippet}"
        )
    matched = sum(1 for o in outcomes if o.get("route_match"))
    print("-" * 78)
    print(f"Route match: {matched}/{len(outcomes)} scenarios as expected.")
    print("Note: SQL = Postgres till T-2 (primary). Pandas/ETL = last-7-days latest campaigns only.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    print(f"AutomaSQL full-workflow run: {len(SCENARIOS)} scenario(s)")
    print("SQL = Postgres till T-2 (primary). ETL/Pandas = latest campaigns (last 7 days).")
    print()

    graph = build_graph()
    outcomes: list[dict] = []
    for scenario in SCENARIOS:
        outcomes.append(run_scenario(graph, scenario))

    print_summary(outcomes)


if __name__ == "__main__":
    main()
