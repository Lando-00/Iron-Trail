from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_owner_key_vault_grant_is_declared_in_iac_and_defaults_off() -> None:
    """The vault uses RBAC, so no human can read the beta secrets unless a role
    is granted. That grant must be in the templates rather than applied by hand,
    and must be present on both the full-deploy and Stage C2 patch paths."""
    main = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
    application = (ROOT / "infra" / "modules" / "application.bicep").read_text(
        encoding="utf-8"
    )
    patch = (ROOT / "infra" / "modules" / "stage_c2_patch.bicep").read_text(
        encoding="utf-8"
    )
    parameters = (ROOT / "infra" / "main.parameters.json").read_text(encoding="utf-8")

    for template in (main, application, patch):
        assert "param grantOwnerKeyVaultAccess string = 'false'" in template

    # Both deployment paths must honour it, not just the full deploy.
    assert "grantOwnerKeyVaultAccess: grantOwnerKeyVaultAccess" in main
    assert main.count("grantOwnerKeyVaultAccess: grantOwnerKeyVaultAccess") == 2
    assert "toLower(grantOwnerKeyVaultAccess) == 'true'" in application
    assert "toLower(grantOwnerKeyVaultAccess) == 'true'" in patch

    # Least privilege: Key Vault Secrets User only, bound to the owner.
    assert "4633458b-17de-408a-b874-0445c86b69e6" in patch
    assert "principalId: ownerObjectId" in patch
    assert "principalType: 'User'" in patch

    assert "IRONTRAIL_GRANT_OWNER_KV_ACCESS" in parameters


def test_stage_c_bicep_uses_matching_lifecycle_and_health_paths() -> None:
    application = (ROOT / "infra" / "modules" / "application.bicep").read_text(
        encoding="utf-8"
    )

    assert "'datasets/raw/'" in application
    assert "'datasets/normalized/'" in application
    assert application.count("path: '/_stcore/health'") == 2
    assert "publicNetworkAccess: 'Enabled'" in application
    assert "defaultAction: 'Allow'" in application
    assert "allowSharedKeyAccess: false" in application
    assert "allowBlobPublicAccess: false" in application


def test_stage_c2_bicep_is_staged_and_fail_closed() -> None:
    application = (ROOT / "infra" / "modules" / "application.bicep").read_text(
        encoding="utf-8"
    )
    patch = (ROOT / "infra" / "modules" / "stage_c2_patch.bicep").read_text(
        encoding="utf-8"
    )
    main = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
    parameters = (ROOT / "infra" / "main.parameters.json").read_text(encoding="utf-8")

    assert "toLower(authReady) == 'true' ? 'AllowAnonymous' : 'Return401'" in application
    assert "name: 'IRONTRAIL_AUTH_PROVIDERS'" in application
    assert "googleAuthConfigured ? 'aad,google' : 'aad'" in application
    assert "name: 'IRONTRAIL_MAX_USERS'" in application
    assert "value: maxUsers" in application
    assert "name: 'IRONTRAIL_AUTH_REVALIDATE_SECONDS'" in application
    assert "value: '5'" in application
    assert "name: 'IRONTRAIL_OWNER_OBJECT_ID'" in application
    assert "name: 'IRONTRAIL_AI_REASONING_EFFORT'" in application
    assert "name: 'IRONTRAIL_AI_MAX_RETRIES'" in application
    assert "value: '0'" in application
    assert application.count("principalId: managedIdentity.outputs.principalId") == 5
    assert application.count("principalType: 'ServicePrincipal'") >= 5
    assert "clientSecretSettingName: 'google-client-secret'" in application
    assert "'openid'" in application
    assert "'email'" in application
    assert "'profile'" in application
    assert "name: 'beta-reveal-seed'" in application
    assert "name: 'IRONTRAIL_BETA_REVEAL_SEED'" in application
    assert "${IRONTRAIL_OWNER_OBJECT_ID}" in parameters
    assert "${IRONTRAIL_AUTH_READY}" in parameters
    assert "${IRONTRAIL_GOOGLE_AUTH_ENABLED}" in parameters
    assert "${IRONTRAIL_STAGE_C2_PATCH_MODE}" in parameters
    assert "${IRONTRAIL_GOOGLE_CLIENT_ID}" in parameters
    assert "${IRONTRAIL_GOOGLE_CLIENT_SECRET}" in parameters
    assert "${IRONTRAIL_MAX_USERS}" in parameters
    assert "${IRONTRAIL_BETA_REVEAL_SEED}" in parameters
    assert "var stageC2PatchEnabled = toLower(stageC2PatchMode) == 'true' || toLower(googleAuthEnabled) == 'true'" in main
    assert "module application './modules/application.bicep' = if (!stageC2PatchEnabled)" in main
    assert "module stageC2Patch './modules/stage_c2_patch.bicep'" in main
    assert "module budget 'br/public:avm/res/consumption/budget/rg-scope:0.1.0' = if (!stageC2PatchEnabled)" in main
    assert "${SERVICE_WEB_IMAGE_NAME}" in parameters
    assert "${WEB_URL}" in parameters
    assert "param currentContainerImage string" in patch
    assert "param currentWebUrl string" in patch
    assert "image: currentContainerImage" in patch
    assert "latestRevision: true" in patch
    assert "weight: 100" in patch
    assert "clientCertificateMode: 'Ignore'" in patch
    assert "exposedPort: 0" in patch
    assert "name: 'google-client-secret'" in patch
    assert "resource betaRevealSeedSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01'" in patch
    assert "name: 'beta-reveal-seed'" in patch
    assert "var keyVaultUri = keyVault.properties.vaultUri" in patch
    assert "name: 'IRONTRAIL_AUTH_PROVIDERS'" in patch
    assert "value: authProviders" in patch
    assert "name: 'IRONTRAIL_AUTH_REVALIDATE_SECONDS'" in patch
    assert "name: 'IRONTRAIL_BETA_REVEAL_SEED'" in patch
    assert "clientSecretSettingName: 'google-client-secret'" in patch
    assert "var googleAuthConfigured = toLower(googleAuthEnabled) == 'true'" in patch
    assert "currentContainerImage == '' ? placeholderImage : currentContainerImage" in application


def test_azd_remote_build_targets_canonical_linux_amd64() -> None:
    azure_yaml = (ROOT / "azure.yaml").read_text(encoding="utf-8")

    assert "platform: linux/amd64" in azure_yaml
    assert "platform: amd64" not in azure_yaml
