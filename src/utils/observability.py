"""OpenTelemetry observability helpers for AutomaSQL.

Provides lightweight span helpers for adding AutomaSQL metadata (scenario id,
route, freshness, status) on top of auto-instrumented spans. No external
observability backend is required.
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)


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
