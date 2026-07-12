from __future__ import annotations

import iron_trail.telemetry as telemetry


def test_telemetry_is_disabled_without_connection_string(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "_CONFIGURED", False)
    assert telemetry.configure_telemetry({}) is False


def test_telemetry_configures_named_logger_once(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(telemetry, "_CONFIGURED", False)

    assert telemetry.configure_telemetry(
        {"APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=test"},
        configurator=lambda **kwargs: calls.append(kwargs),
    )
    assert calls[0]["logger_name"] == "iron_trail"
    assert calls[0]["disable_offline_storage"] is True
    assert calls[0]["enable_live_metrics"] is False
    assert all(
        option["enabled"] is False
        for option in calls[0]["instrumentation_options"].values()
    )
