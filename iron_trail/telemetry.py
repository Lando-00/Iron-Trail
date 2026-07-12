"""Minimal, privacy-conscious Azure Monitor initialization."""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Mapping

_LOCK = threading.Lock()
_CONFIGURED = False


def configure_telemetry(
    environ: Mapping[str, str] | None = None,
    *,
    configurator: Callable[..., None] | None = None,
) -> bool:
    global _CONFIGURED

    env = environ or os.environ
    if not env.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip():
        return False
    if _CONFIGURED:
        return True

    with _LOCK:
        if _CONFIGURED:
            return True
        if configurator is None:
            from azure.monitor.opentelemetry import configure_azure_monitor

            configurator = configure_azure_monitor
        configurator(logger_name="iron_trail")
        logging.getLogger("iron_trail").setLevel(logging.INFO)
        _CONFIGURED = True
        return True

