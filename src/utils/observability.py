"""Arize Phoenix observability for AutomaSQL.

Phoenix is an open-source LLM evaluation and observability tool that runs
locally with no login. This module wires it up so every LangGraph run
(router -> SQL / ETL+pandas -> answer) and every LLM call (router, SQL
engineer, pandas engineer, analyzer, LLM judges) shows up as traces in the
local Phoenix UI.

Quickstart (no login required)::

    uv sync
    uv run phoenix serve        # UI at http://localhost:6006
    uv run python main.py       # traces appear under project "automasql"
    uv run python evals.py      # traces + judge scores

How it works:
  - :func:`setup_phoenix` registers an OpenTelemetry tracer provider that
    exports OTLP spans to the local Phoenix collector and enables
    OpenInference auto-instrumentation for LangChain + OpenAI, so existing
    agents need no code changes to be traced.
  - :func:`span` / :func:`set_span_attributes` add AutomaSQL metadata
    (scenario id, route, freshness, status) on top of the auto-instrumented
    spans.
  - :func:`log_evals_to_phoenix` uploads the evals.py results as a Phoenix
    dataset on a best-effort basis (never fails the eval run).

All helpers are safe no-ops when Phoenix / OpenTelemetry is not installed or
when ``PHOENIX_ENABLED=false``, so the app still runs without observability.
"""
from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

_CONFIGURED = False
_PROVIDER: Any = None
_SESSION: Any = None


def phoenix_enabled() -> bool:
    """Return False only when explicitly disabled via ``PHOENIX_ENABLED``."""
    return os.getenv("PHOENIX_ENABLED", "true").lower() not in ("0", "false", "no", "off")


def phoenix_project(project_name: str | None = None) -> str:
    """Resolve the Phoenix project name (env ``PHOENIX_PROJECT_NAME``)."""
    return project_name or os.getenv("PHOENIX_PROJECT_NAME", "automasql")


def phoenix_ui_url() -> str:
    """Public URL of the local Phoenix UI (no login required)."""
    host = os.getenv("PHOENIX_HOST", "localhost")
    port = os.getenv("PHOENIX_PORT", "6006")
    return f"http://{host}:{port}"


def phoenix_endpoint() -> str:
    """OTLP collector endpoint spans are exported to."""
    if os.getenv("PHOENIX_COLLECTOR_ENDPOINT"):
        return os.environ["PHOENIX_COLLECTOR_ENDPOINT"]
    host = os.getenv("PHOENIX_HOST", "localhost")
    port = os.getenv("PHOENIX_PORT", "6006")
    return f"http://{host}:{port}/v1/traces"


def setup_phoenix(
    project_name: str | None = None,
    *,
    launch_ui: bool | None = None,
) -> Any:
    """Register Phoenix tracing with OpenInference auto-instrumentation.

    Args:
        project_name: Phoenix project traces are grouped under.
        launch_ui: when True, also start ``phoenix.launch_app()`` in this
            process. Defaults to the ``PHOENIX_LAUNCH_UI`` env var (false
            unless set), since the usual flow is ``uv run phoenix serve``
            in a separate terminal.

    Returns:
        The tracer provider, or None when disabled / not installed.
    """
    global _CONFIGURED, _PROVIDER, _SESSION
    if _CONFIGURED:
        return _PROVIDER
    if not phoenix_enabled():
        logger.info("Phoenix tracing disabled (PHOENIX_ENABLED=false).")
        _CONFIGURED = True
        return None

    name = phoenix_project(project_name)
    endpoint = phoenix_endpoint()
    try:
        from phoenix.otel import register
    except ImportError:
        logger.warning(
            "Phoenix is not installed; skipping tracing. Install with: "
            "uv sync  (requires arize-phoenix). Traces will not be exported."
        )
        _CONFIGURED = True
        return None

    try:
        _PROVIDER = register(
            project_name=name,
            endpoint=endpoint,
            auto_instrument=True,
        )
        logger.info("Phoenix tracing enabled: project=%r endpoint=%s", name, endpoint)
    except Exception as exc:
        logger.warning("Failed to register Phoenix tracing: %s", exc)
        _CONFIGURED = True
        return None

    if launch_ui is None:
        launch_ui = os.getenv("PHOENIX_LAUNCH_UI", "false").lower() in ("1", "true", "yes", "on")
    if launch_ui:
        try:
            import phoenix as px

            _SESSION = px.launch_app(
                host=os.getenv("PHOENIX_HOST", "localhost"),
                port=int(os.getenv("PHOENIX_PORT", "6006")),
            )
            logger.info("Phoenix UI launched at %s", phoenix_ui_url())
        except Exception as exc:
            logger.warning("Could not launch Phoenix UI in-process: %s", exc)

    _CONFIGURED = True
    return _PROVIDER


@contextlib.contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """OpenTelemetry span carrying AutomaSQL metadata (no-op if OTel missing)."""
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("automasql")
        with tracer.start_as_current_span(name) as current:
            if attributes:
                for key, value in attributes.items():
                    if value is None:
                        continue
                    try:
                        current.set_attribute(
                            key,
                            value if isinstance(value, (bool, int, float, str)) else str(value),
                        )
                    except Exception:
                        pass
            yield current
    except Exception:
        yield None


def set_span_attributes(attributes: dict[str, Any]) -> None:
    """Attach attributes to the current span (no-op if OTel missing)."""
    try:
        from opentelemetry import trace

        current = trace.get_current_span()
        for key, value in attributes.items():
            if value is None:
                continue
            try:
                current.set_attribute(
                    key, value if isinstance(value, (bool, int, float, str)) else str(value)
                )
            except Exception:
                pass
    except Exception:
        pass


def log_evals_to_phoenix(records: list[dict[str, Any]], *, dataset_name: str = "automasql-evals") -> None:
    """Upload evals.py results as a Phoenix dataset (best-effort, never raises).

    Requires the local Phoenix server (``uv run phoenix serve``). Each record
    becomes one dataset example with the question as input, the answer plus
    judge scores as outputs, and route metadata.
    """
    if not records:
        return
    if not phoenix_enabled():
        return
    try:
        import pandas as pd
        import phoenix as px
    except ImportError:
        logger.warning("Skipping Phoenix dataset upload: phoenix/pandas not installed.")
        return
    try:
        rows: list[dict[str, Any]] = []
        for record in records:
            evaluations = record.get("evaluations", {}) or {}

            def _score(key: str) -> Any:
                entry = evaluations.get(key) or {}
                return entry.get("score")

            rows.append(
                {
                    "scenario_id": record.get("scenario_id"),
                    "question": record.get("question"),
                    "answer": record.get("answer"),
                    "expected_route": record.get("expected_route"),
                    "actual_route": record.get("actual_route"),
                    "route_match": record.get("route_match"),
                    "status": record.get("status"),
                    "correctness_score": _score("correctness"),
                    "answer_relevance_score": _score("answer_relevance"),
                    "hallucination_score": _score("hallucination"),
                }
            )
        client = px.Client()
        client.upload_dataset(
            dataframe=pd.DataFrame(rows),
            dataset_name=dataset_name,
            input_keys=["question"],
            output_keys=["answer", "correctness_score", "answer_relevance_score", "hallucination_score"],
            dataset_description="AutomaSQL evals.py runs: route match, status, and LLM-judge scores.",
        )
        logger.info("Uploaded %d eval record(s) to Phoenix dataset %r.", len(rows), dataset_name)
    except Exception as exc:
        logger.warning("Phoenix dataset upload skipped (is `phoenix serve` running?): %s", exc)
