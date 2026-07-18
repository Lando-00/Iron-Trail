from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_stage_c_bicep_uses_matching_lifecycle_and_health_paths() -> None:
    application = (ROOT / "infra" / "modules" / "application.bicep").read_text(
        encoding="utf-8"
    )

    assert "'datasets/raw/'" in application
    assert "'datasets/normalized/'" in application
    assert application.count("path: '/_stcore/health'") == 2


def test_stage_c_bicep_is_owner_only_and_fail_closed() -> None:
    application = (ROOT / "infra" / "modules" / "application.bicep").read_text(
        encoding="utf-8"
    )
    parameters = (ROOT / "infra" / "main.parameters.json").read_text(encoding="utf-8")

    assert "toLower(authReady) == 'true' ? 'AllowAnonymous' : 'Return401'" in application
    assert "name: 'IRONTRAIL_AUTH_PROVIDERS'" in application
    assert "value: 'aad'" in application
    assert "name: 'IRONTRAIL_MAX_USERS'" in application
    assert "value: '1'" in application
    assert "name: 'IRONTRAIL_OWNER_OBJECT_ID'" in application
    assert "name: 'IRONTRAIL_AI_REASONING_EFFORT'" in application
    assert "name: 'IRONTRAIL_AI_MAX_RETRIES'" in application
    assert "value: '0'" in application
    assert application.count("principalId: managedIdentity.outputs.principalId") == 5
    assert application.count("principalType: 'ServicePrincipal'") >= 5
    assert "${IRONTRAIL_OWNER_OBJECT_ID}" in parameters
    assert "${IRONTRAIL_AUTH_READY}" in parameters


def test_azd_remote_build_targets_canonical_linux_amd64() -> None:
    azure_yaml = (ROOT / "azure.yaml").read_text(encoding="utf-8")

    assert "platform: linux/amd64" in azure_yaml
    assert "platform: amd64" not in azure_yaml
