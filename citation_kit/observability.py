"""Observability hooks: pluggable logger + optional metric callbacks.

Default behavior: standard ``logging`` at DEBUG level on the
``citation_kit`` logger. No metric reporting unless callbacks are wired.

Wire metrics::

    from citation_kit import set_metric_hook

    def to_prometheus(name: str, value: float, **labels) -> None:
        my_counter.labels(**labels).inc(value)

    set_metric_hook(to_prometheus)

Recognized metric names:
  * ``citation_kit.register``        — value=1 each time a record is registered
  * ``citation_kit.dedup_hit``       — value=1 each time register hits an existing cite_id
  * ``citation_kit.placeholder_seen`` — value=1 each time renderer sees a known placeholder
  * ``citation_kit.placeholder_orphan`` — value=1 each time an unknown placeholder is seen
  * ``citation_kit.references_emitted`` — value=N at end of rendering for unique cites count

All hooks are optional and dirt-cheap when unset (single dict lookup).
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger("citation_kit")


# Single global metric hook. Mutually exclusive with thread-local for v0.2.
# The hook receives (name, value, **labels). Label keys depend on metric.
_METRIC_HOOK: Callable[..., None] | None = None


def set_metric_hook(fn: Callable[..., None] | None) -> None:
    """Install a metric callback. Pass None to disable."""
    global _METRIC_HOOK
    _METRIC_HOOK = fn


def emit(name: str, value: float = 1.0, **labels) -> None:
    """Internal — call from library code at metric points."""
    hook = _METRIC_HOOK
    if hook is not None:
        try:
            hook(name, value, **labels)
        except Exception:  # noqa: BLE001
            logger.exception("metric hook %s raised", name)
