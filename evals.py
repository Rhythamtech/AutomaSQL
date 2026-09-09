from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openevals.llm import create_llm_as_judge
from openevals.prompts import (
    ANSWER_RELEVANCE_PROMPT,
    CORRECTNESS_PROMPT,
    HALLUCINATION_PROMPT,
)

from src.graph.orchestrator import build_graph
from src.utils.observability import span


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "sql-top-customers",
        "name": "Top customers by order value",
        "question": "Who are our top 5 customers by total order value?",
        "force_refresh": False,
        "expected_route": "sql",
    },
    {
        "id": "sql-top-products",
        "name": "Top products by revenue",
        "question": "What are the top 5 products by revenue?",
        "force_refresh": False,
        "expected_route": "sql",
    },
    {
        "id": "sql-payments-returns",
        "name": "Payments and returns health",
        "question": "How many payments succeeded vs failed by payment method, and what are the most common return reasons?",
        "force_refresh": False,
        "expected_route": "sql",
    },
    {
        "id": "sql-historical-campaigns",
        "name": "Historical campaign ROI",
        "question": "Show top 5 historical campaigns by ROI with highest revenue using database data till T-2",
        "force_refresh": False,
        "expected_route": "sql",
    },
    {
        "id": "etl-latest-campaigns",
        "name": "Latest campaigns by ROI",
        "question": "Show the latest campaigns by ROI in the last 7 days",
        "force_refresh": False,
        "expected_route": "pandas",
    },
    {
        "id": "etl-active-refresh",
        "name": "Active campaigns with forced refresh",
        "question": "Which active campaigns are running right now? Show current CTR and profit",
        "force_refresh": True,
        "expected_route": "pandas",
    },
]

OUTPUT_DIR = Path("data/evals")
MAX_CONTEXT_CHARS = 8_000


def _serialize(value: object) -> str:
    if value is None:
        return "<no query result>"
    if hasattr(value, "head") and hasattr(value, "to_string"):
        try:
            value = value.head(20).to_string(index=False)
        except Exception:
            value = str(value)
    elif isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, default=str, sort_keys=True)
    else:
        value = str(value)
    return value if len(value) <= MAX_CONTEXT_CHARS else value[:MAX_CONTEXT_CHARS] + "\n...[truncated]"


def _metric(result: dict[str, Any]) -> dict[str, Any]:
    return {"score": result.get("score"), "comment": result.get("comment")}


def _run_evaluators(
    *,
    evaluators: dict[str, Any],
    question: str,
    answer: str,
    context: str,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name, evaluator in evaluators.items():
        try:
            kwargs: dict[str, Any] = {"inputs": question, "outputs": answer}
            if name == "correctness":
                kwargs["reference_outputs"] = context
            elif name == "hallucination":
                kwargs["context"] = context
            results[name] = _metric(evaluator(**kwargs))
        except Exception as exc:
            results[name] = {"score": None, "comment": f"Evaluator failed: {exc}"}
    return results


def _evaluate_scenario(graph: Any, scenario: dict[str, Any], evaluators: dict[str, Any]) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    record: dict[str, Any] = {
        "started_at": started_at,
        "scenario_id": scenario["id"],
        "scenario_name": scenario["name"],
        "question": scenario["question"],
        "force_refresh": scenario["force_refresh"],
        "expected_route": scenario["expected_route"],
        "actual_route": None,
        "route_match": False,
        "status": None,
        "error": None,
        "answer": "",
        "query_result_context": "<no query result>",
        "evaluations": {},
    }
    try:
        with span(
            f"eval.{scenario['id']}",
            {
                "automasql.scenario_id": scenario["id"],
                "automasql.question": scenario["question"],
                "automasql.expected_route": scenario.get("expected_route"),
                "automasql.force_refresh": scenario.get("force_refresh"),
            },
        ):
            result = graph.invoke(
                {
                    "question": scenario["question"],
                    "force_refresh": scenario["force_refresh"],
                }
            )
        record.update(
            {
                "actual_route": result.get("route"),
                "route_match": result.get("route") == scenario["expected_route"],
                "status": result.get("status"),
                "error": result.get("error"),
                "answer": str(result.get("answer") or ""),
                "query_result_context": _serialize(result.get("query_result")),
            }
        )
    except Exception as exc:
        record.update({"status": "exception", "error": str(exc)})

    if record["answer"] and record["query_result_context"] != "<no query result>":
        record["evaluations"] = _run_evaluators(
            evaluators=evaluators,
            question=record["question"],
            answer=record["answer"],
            context=record["query_result_context"],
        )
    else:
        record["evaluations"] = {
            name: {"score": None, "comment": "Skipped because no answer or query result was produced."}
            for name in evaluators
        }
    return record


def _save_results(records: list[dict[str, Any]]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = OUTPUT_DIR / f"evals_{timestamp}.json"
    csv_path = OUTPUT_DIR / f"evals_{timestamp}.csv"
    json_path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")

    fieldnames = [
        "scenario_id",
        "scenario_name",
        "question",
        "expected_route",
        "actual_route",
        "route_match",
        "status",
        "error",
        "answer",
        "correctness_score",
        "answer_relevance_score",
        "hallucination_score",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            evaluations = record["evaluations"]
            writer.writerow(
                {
                    **{field: record.get(field) for field in fieldnames[:9]},
                    "correctness_score": evaluations["correctness"]["score"],
                    "answer_relevance_score": evaluations["answer_relevance"]["score"],
                    "hallucination_score": evaluations["hallucination"]["score"],
                }
            )
    return json_path, csv_path


def main() -> None:
    load_dotenv()
    model = os.getenv("OPENAI_EVAL_MODEL")
    if not model or model == "xxxxxxxxxxx":
        raise RuntimeError("Set OPENAI_EVAL_MODEL in .env before running evals.py")

    evaluators = {
        "correctness": create_llm_as_judge(
            prompt=CORRECTNESS_PROMPT,
            feedback_key="correctness",
            model=model,
        ),
        "answer_relevance": create_llm_as_judge(
            prompt=ANSWER_RELEVANCE_PROMPT,
            feedback_key="answer_relevance",
            model=model,
        ),
        "hallucination": create_llm_as_judge(
            prompt=HALLUCINATION_PROMPT,
            feedback_key="hallucination",
            model=model,
        ),
    }
    graph = build_graph()
    records = [_evaluate_scenario(graph, scenario, evaluators) for scenario in SCENARIOS]
    json_path, csv_path = _save_results(records)

    successful = sum(1 for record in records if record["evaluations"]["correctness"]["score"] is not None)
    print(f"Evaluated {len(records)} scenarios; {successful} produced judge scores.")
    print(f"JSON results: {json_path}")
    print(f"CSV results:  {csv_path}")


if __name__ == "__main__":
    main()
