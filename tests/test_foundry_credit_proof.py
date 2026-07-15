from __future__ import annotations

import importlib.util
import json
import sys
from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from iron_trail.coach.providers import Message, TokenUsage

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "foundry_credit_proof.py"
_SPEC = importlib.util.spec_from_file_location("foundry_credit_proof", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
proof = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = proof
_SPEC.loader.exec_module(proof)


class FakeProvider:
    def __init__(self, response_text: str = "response text must not persist") -> None:
        self.response_text = response_text
        self.calls = 0
        self.last_usage: TokenUsage | None = None
        self.last_request_id: str | None = None
        self.last_response_id: str | None = None

    def chat(self, messages: list[Message], *, timeout: float = 120.0) -> str:
        self.calls += 1
        self.last_usage = TokenUsage(input_tokens=100 + self.calls, output_tokens=20)
        self.last_request_id = f"request-{self.calls}"
        self.last_response_id = f"response-{self.calls}"
        return self.response_text


def fixed_clock() -> datetime:
    return datetime(2026, 7, 13, 21, 30, tzinfo=UTC)


def target() -> dict:
    return {
        "subscription_name": "Visual Studio Enterprise Subscription",
        "subscription_id": "subscription-id",
        "tenant_id": "tenant-id",
        "resource_group": "rg-IronTrail",
        "account": "irontrail-resource",
        "project": "irontrail",
        "endpoint": "https://irontrail-resource.cognitiveservices.azure.com/",
        "region": "swedencentral",
        "deployment_name": "gpt-5-mini",
        "model_name": "gpt-5-mini",
        "model_version": "2025-08-07",
        "model_format": "OpenAI",
        "sku": "DataZoneStandard",
        "capacity": 10,
        "rai_policy": "Microsoft.DefaultV2",
        "version_upgrade_option": "OnceCurrentVersionExpired",
    }


def identity() -> dict:
    return {"object_id": "object-id", "upn": "user@example.invalid"}


def billing() -> dict:
    return {
        "observed_at": fixed_clock().isoformat(),
        "source_url": "https://portal.azure.com/",
        "qualifier": "remaining_credit",
        "subscription_name": "Visual Studio Enterprise Subscription",
        "subscription_id": "subscription-id",
        "remaining_credit_eur": "100.00",
    }


def pricing(
    *,
    input_eur_per_million: str = "0.2413",
    output_eur_per_million: str = "1.9307",
) -> dict:
    return {
        "observed_at": fixed_clock().isoformat(),
        "source_url": "https://prices.azure.com/api/retail/prices?currencyCode=EUR",
        "source_kind": "azure-retail-prices-api",
        "currency": "EUR",
        "input_meter": "GPT 5 Mini Inpt DZone 1M Tokens",
        "output_meter": "GPT 5 Mini outpt DZone 1M Tokens",
        "input_eur_per_million": input_eur_per_million,
        "output_eur_per_million": output_eur_per_million,
        "input_effective_start_date": "2025-08-01T00:00:00Z",
        "output_effective_start_date": "2025-08-01T00:00:00Z",
    }


def quota_observation(current_value: int) -> dict:
    return {
        "observed_at": fixed_clock().isoformat(),
        "subscription_id": "subscription-id",
        "location": "swedencentral",
        "usage_name": "OpenAI.DataZoneStandard.gpt-5-mini",
        "current_value": current_value,
        "limit": 300,
    }


def cost_evidence(
    *,
    request_id: str = "baseline-request",
    rows: list[list] | None = None,
) -> dict:
    return {
        "observed_at": fixed_clock().isoformat(),
        "request_id": request_id,
        "query": proof.expected_cost_query("rg-IronTrail"),
        "columns": [
            {"name": "Cost", "type": "Number"},
            {"name": "ServiceName", "type": "String"},
            {"name": "ResourceId", "type": "String"},
            {"name": "Currency", "type": "String"},
        ],
        "rows": rows or [],
    }


def initialize_ready_ledger(path: Path) -> dict:
    proof.initialize_ledger(
        path,
        target=target(),
        identity=identity(),
        billing_preflight=billing(),
        pricing=pricing(),
        quota_baseline=quota_observation(0),
        cost_baseline=cost_evidence(),
        clock=fixed_clock,
    )
    ledger = proof.load_ledger(path)
    proof.record_deployment_intent(
        path,
        proof.expected_deployment_payload(ledger),
        clock=fixed_clock,
    )
    proof.record_deployment_submitted(path, request_id="arm-request", clock=fixed_clock)
    ledger = proof.load_ledger(path)
    proof.record_deployment_readback(
        path,
        deployment_readback(ledger),
        account_readback(ledger),
        clock=fixed_clock,
    )
    proof.verify_quota_convergence(
        path,
        quota_reader=lambda _: quota_observation(10),
        sleep=lambda _: None,
        monotonic=lambda: 0.0,
        clock=fixed_clock,
    )
    return proof.load_ledger(path)


def deployment_readback(ledger: dict) -> dict:
    target_values = ledger["target"]
    return {
        "id": target_values["deployment_resource_id"],
        "name": target_values["deployment_name"],
        "sku": {"name": target_values["sku"], "capacity": target_values["capacity"]},
        "properties": {
            "provisioningState": "Succeeded",
            "model": {
                "format": target_values["model_format"],
                "name": target_values["model_name"],
                "version": target_values["model_version"],
            },
            "raiPolicyName": target_values["rai_policy"],
            "versionUpgradeOption": target_values["version_upgrade_option"],
        },
    }


def account_readback(ledger: dict) -> dict:
    target_values = ledger["target"]
    return {
        "id": target_values["account_resource_id"],
        "location": target_values["region"],
        "properties": {"provisioningState": "Succeeded"},
    }


def test_proof_runs_ten_calls_without_persisting_response_text(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    initialize_ready_ledger(ledger_path)
    provider = FakeProvider()

    ledger = proof.run_proof(
        ledger_path,
        provider=provider,
        quota_reader=lambda _: quota_observation(10),
        identity_checker=lambda _: None,
        sleep=lambda _: None,
        clock=fixed_clock,
    )

    assert provider.calls == 10
    assert ledger["outcome"] == "awaiting_cost_confirmation"
    assert all(call["state"] == "completed" for call in ledger["calls"])
    assert provider.response_text not in ledger_path.read_text(encoding="utf-8")


def test_resume_skips_completed_call_indices(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    ledger = initialize_ready_ledger(ledger_path)
    ledger["calls"][0].update(
        {
            "state": "completed",
            "attempts": 1,
            "submitted_at": fixed_clock().isoformat(),
            "completed_at": fixed_clock().isoformat(),
            "request_id": "existing-request",
            "response_id": "existing-response",
            "input_tokens": 100,
            "output_tokens": 20,
            "estimated_cost_eur": proof.decimal_text(
                proof.buffered_call_cost(
                    100,
                    20,
                    input_eur_per_million=proof.decimal_value(
                        ledger["pricing"]["input_eur_per_million"],
                        field="input",
                    ),
                    output_eur_per_million=proof.decimal_value(
                        ledger["pricing"]["output_eur_per_million"],
                        field="output",
                    ),
                )
            ),
        }
    )
    ledger["quota"]["call_checks"].append(
        {"call_index": 1, "observation": quota_observation(10)}
    )
    proof.save_ledger(ledger_path, ledger, clock=fixed_clock)
    provider = FakeProvider()

    resumed = proof.run_proof(
        ledger_path,
        provider=provider,
        quota_reader=lambda _: quota_observation(10),
        identity_checker=lambda _: None,
        sleep=lambda _: None,
        clock=fixed_clock,
    )

    assert provider.calls == 9
    assert resumed["calls"][0]["request_id"] == "existing-request"
    assert all(call["state"] == "completed" for call in resumed["calls"])


def test_inflight_call_becomes_uncertain_and_is_not_replayed(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    ledger = initialize_ready_ledger(ledger_path)
    ledger["calls"][0]["state"] = "inflight"
    ledger["calls"][0]["attempts"] = 1
    ledger["calls"][0]["submitted_at"] = fixed_clock().isoformat()
    ledger["quota"]["call_checks"].append(
        {"call_index": 1, "observation": quota_observation(10)}
    )
    proof.save_ledger(ledger_path, ledger, clock=fixed_clock)
    provider = FakeProvider()

    with pytest.raises(proof.ProofError, match="marked uncertain"):
        proof.run_proof(
            ledger_path,
            provider=provider,
            quota_reader=lambda _: quota_observation(10),
            identity_checker=lambda _: None,
            sleep=lambda _: None,
            clock=fixed_clock,
        )

    reloaded = proof.load_ledger(ledger_path)
    assert provider.calls == 0
    assert reloaded["calls"][0]["state"] == "uncertain"
    assert reloaded["calls"][0]["error_code"] == "resume_after_inflight"


def test_pricing_ceiling_blocks_ledger_creation(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"

    with pytest.raises(proof.ProofError, match="exceeds"):
        proof.initialize_ledger(
            ledger_path,
            target=target(),
            identity=identity(),
            billing_preflight=billing(),
            pricing=pricing(
                input_eur_per_million="100",
                output_eur_per_million="100",
            ),
            quota_baseline=quota_observation(0),
            cost_baseline=cost_evidence(),
            clock=fixed_clock,
        )

    assert not ledger_path.exists()


def test_synthetic_prompt_guard_rejects_workout_context() -> None:
    messages = proof.build_synthetic_messages(1, "nonce")

    assert len("\n".join(message.content for message in messages).encode("ascii")) < 1_000
    with pytest.raises(proof.ProofError, match="forbidden context"):
        proof.validate_synthetic_messages([Message("user", "Summarize this Hevy workout.")])


def test_cost_check_records_query_without_response_content(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    initialized = initialize_ready_ledger(ledger_path)
    proof.run_proof(
        ledger_path,
        provider=FakeProvider(),
        quota_reader=lambda _: quota_observation(10),
        identity_checker=lambda _: None,
        sleep=lambda _: None,
        clock=fixed_clock,
    )
    initialized = proof.load_ledger(ledger_path)
    evidence = cost_evidence(
        request_id="cost-request",
        rows=[
            [
                0.001,
                "Foundry Models",
                initialized["target"]["account_resource_id"],
                "EUR",
            ]
        ],
    )

    ledger = proof.check_live_cost(
        ledger_path,
        cost_reader=lambda _: evidence,
        clock=fixed_clock,
    )

    serialized = json.dumps(ledger)
    assert ledger["outcome"] == "success"
    assert "response text must not persist" not in serialized


def test_deployment_timeout_polls_without_second_put(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    proof.initialize_ledger(
        ledger_path,
        target=target(),
        identity=identity(),
        billing_preflight=billing(),
        pricing=pricing(),
        quota_baseline=quota_observation(0),
        cost_baseline=cost_evidence(),
        clock=fixed_clock,
    )
    calls: list[str] = []

    def requester(_credential, method, url, body, _timeout):
        calls.append(method)
        if method == "PUT":
            raise TimeoutError("ambiguous")
        ledger = proof.load_ledger(ledger_path)
        if url == proof.account_url(ledger["target"]):
            return proof.ArmResponse(200, {}, account_readback(ledger))
        if calls.count("GET") == 1:
            return proof.ArmResponse(404, {}, {"error": {"code": "NotFound"}})
        return proof.ArmResponse(200, {}, deployment_readback(ledger))

    ledger = proof.deploy_model_once(
        ledger_path,
        requester=requester,
        credential_factory=lambda _ledger, _scope: object(),
        quota_reader=lambda _: quota_observation(0),
        identity_checker=lambda _: None,
        sleep=lambda _: None,
        monotonic=lambda: 0.0,
        clock=fixed_clock,
    )

    assert calls.count("PUT") == 1
    assert ledger["deployment"]["state"] == "succeeded"


def test_access_token_claims_must_match_tenant_and_object() -> None:
    claims = {"tid": "tenant-id", "oid": "object-id"}
    payload = urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    token = f"header.{payload}.signature"

    proof.validate_access_token_claims(
        token,
        tenant_id="tenant-id",
        object_id="object-id",
    )
    with pytest.raises(proof.ProofError, match="identity mismatch"):
        proof.validate_access_token_claims(
            token,
            tenant_id="tenant-id",
            object_id="other-object",
        )


def test_apim_request_id_prevents_retry_classification() -> None:
    exception = RuntimeError("rate limited")
    exception.response = SimpleNamespace(headers={"apim-request-id": "request-123"})

    assert proof.exception_request_id(exception) == "request-123"


def test_ledger_rejects_reordered_call_indices(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    ledger = initialize_ready_ledger(ledger_path)
    ledger["calls"][0], ledger["calls"][1] = ledger["calls"][1], ledger["calls"][0]

    with pytest.raises(proof.ProofError, match="ordered"):
        proof.save_ledger(ledger_path, ledger, clock=fixed_clock)


def test_ledger_lock_refuses_concurrent_holder(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"

    with proof.exclusive_ledger_lock(ledger_path):
        with pytest.raises(proof.ProofError, match="Another process"):
            with proof.exclusive_ledger_lock(ledger_path):
                pass


def test_forged_completed_call_is_rejected(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    ledger = initialize_ready_ledger(ledger_path)
    ledger["calls"][0]["state"] = "completed"

    with pytest.raises(proof.ProofError, match="token usage is invalid"):
        proof.save_ledger(ledger_path, ledger, clock=fixed_clock)


def test_forged_success_outcome_is_rejected(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    ledger = initialize_ready_ledger(ledger_path)
    ledger["outcome"] = "success"

    with pytest.raises(proof.ProofError, match="success lacks"):
        proof.save_ledger(ledger_path, ledger, clock=fixed_clock)


def test_cost_check_is_blocked_before_proof_calls(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    initialize_ready_ledger(ledger_path)

    with pytest.raises(proof.ProofError, match="not allowed"):
        proof.check_live_cost(
            ledger_path,
            cost_reader=lambda _: cost_evidence(request_id="cost-request"),
            clock=fixed_clock,
        )


def test_live_quota_change_blocks_call_before_provider(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    initialize_ready_ledger(ledger_path)
    provider = FakeProvider()

    with pytest.raises(proof.ProofError, match="Live quota changed"):
        proof.run_proof(
            ledger_path,
            provider=provider,
            quota_reader=lambda _: quota_observation(0),
            identity_checker=lambda _: None,
            sleep=lambda _: None,
            clock=fixed_clock,
        )

    assert provider.calls == 0


def test_unexpected_target_service_cost_is_rejected(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    ledger = initialize_ready_ledger(ledger_path)
    proof.run_proof(
        ledger_path,
        provider=FakeProvider(),
        quota_reader=lambda _: quota_observation(10),
        identity_checker=lambda _: None,
        sleep=lambda _: None,
        clock=fixed_clock,
    )
    evidence = cost_evidence(
        request_id="cost-request",
        rows=[
            [
                0.001,
                "Unexpected Service",
                ledger["target"]["account_resource_id"],
                "EUR",
            ]
        ],
    )

    with pytest.raises(proof.ProofError, match="unexpected service"):
        proof.check_live_cost(
            ledger_path,
            cost_reader=lambda _: evidence,
            clock=fixed_clock,
        )


def test_terminal_proof_can_record_cost_without_becoming_success(tmp_path: Path) -> None:
    ledger_path = tmp_path / "proof.json"
    ledger = initialize_ready_ledger(ledger_path)
    ledger["calls"][0]["state"] = "inflight"
    ledger["calls"][0]["attempts"] = 1
    ledger["calls"][0]["submitted_at"] = fixed_clock().isoformat()
    ledger["quota"]["call_checks"].append(
        {"call_index": 1, "observation": quota_observation(10)}
    )
    proof.save_ledger(ledger_path, ledger, clock=fixed_clock)
    with pytest.raises(proof.ProofError, match="marked uncertain"):
        proof.run_proof(
            ledger_path,
            provider=FakeProvider(),
            quota_reader=lambda _: quota_observation(10),
            identity_checker=lambda _: None,
            sleep=lambda _: None,
            clock=fixed_clock,
        )
    stopped = proof.load_ledger(ledger_path)
    evidence = cost_evidence(
        request_id="terminal-cost-request",
        rows=[
            [
                0.001,
                "Foundry Models",
                stopped["target"]["account_resource_id"],
                "EUR",
            ]
        ],
    )

    checked = proof.check_live_cost(
        ledger_path,
        cost_reader=lambda _: evidence,
        clock=fixed_clock,
    )

    assert checked["outcome"] == "stopped_uncertain"
    assert checked["cost_checks"][-1]["foundry_charge_observed"] is True
