from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_stage_c2_whatif.py"
SPEC = importlib.util.spec_from_file_location("validate_stage_c2_whatif", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
whatif = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = whatif
SPEC.loader.exec_module(whatif)


SUBSCRIPTION = "sub"
RESOURCE_GROUP = "rg-IronTrail"
PREFIX = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}/providers/"
)
CONTAINER_APP = f"{PREFIX}Microsoft.App/containerApps/ca-irontrail-example"
AUTH_CONFIG = f"{CONTAINER_APP}/authConfigs/current"
GOOGLE_SECRET = (
    f"{PREFIX}Microsoft.KeyVault/vaults/kv-irontrail-example/"
    "secrets/google-client-secret"
)
BETA_REVEAL_SECRET = (
    f"{PREFIX}Microsoft.KeyVault/vaults/kv-irontrail-example/"
    "secrets/beta-reveal-seed"
)


def change(kind: str, resource_id: str, *deltas: tuple[str, str]) -> dict[str, object]:
    return {
        "changeType": kind,
        "resourceId": resource_id,
        "delta": [
            {"path": path, "propertyChangeType": property_change}
            for path, property_change in deltas
        ],
    }


def validate(*changes: dict[str, object], owner_object_id: str | None = None) -> list[str]:
    return whatif.validate_stage_c2_whatif(
        list(changes),
        subscription_id=SUBSCRIPTION,
        resource_group=RESOURCE_GROUP,
        owner_object_id=owner_object_id,
        storage_account_name="stirontrailexample",
    )


OWNER = "9f2b1274-9c68-42a9-979e-9570fbc3ff9e"
KV_ROLE_ASSIGNMENT = (
    f"{PREFIX}Microsoft.KeyVault/vaults/kv-irontrail-example/"
    "providers/Microsoft.Authorization/roleAssignments/"
    "11111111-2222-3333-4444-555555555555"
)
STORAGE_ACCOUNT = (
    f"{PREFIX}Microsoft.Storage/storageAccounts/stirontrailexample"
)
STORAGE_ROLE_ASSIGNMENT = (
    f"{STORAGE_ACCOUNT}/providers/Microsoft.Authorization/roleAssignments/"
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
)


def role_assignment_change(
    *,
    kind: str = "Create",
    role_id: str = whatif.KEY_VAULT_SECRETS_USER_ROLE_ID,
    principal_id: str = OWNER,
) -> dict[str, object]:
    return {
        "changeType": kind,
        "resourceId": KV_ROLE_ASSIGNMENT,
        "after": {
            "properties": {
                "roleDefinitionId": (
                    f"/subscriptions/{SUBSCRIPTION}/providers/"
                    f"Microsoft.Authorization/roleDefinitions/{role_id}"
                ),
                "principalId": principal_id,
            }
        },
    }


def storage_role_assignment_change(
    *,
    kind: str = "Create",
    role_id: str = whatif.STORAGE_TABLE_DATA_READER_ROLE_ID,
    principal_id: str = OWNER,
    resource_id: str = STORAGE_ROLE_ASSIGNMENT,
) -> dict[str, object]:
    snapshot = {
        "properties": {
            "roleDefinitionId": (
                f"/subscriptions/{SUBSCRIPTION}/providers/"
                f"Microsoft.Authorization/roleDefinitions/{role_id}"
            ),
            "principalId": principal_id,
        }
    }
    result: dict[str, object] = {
        "changeType": kind,
        "resourceId": resource_id,
    }
    result["before" if kind == "Delete" else "after"] = snapshot
    return result


def test_owner_key_vault_grant_is_allowed_when_expected() -> None:
    assert validate(role_assignment_change(), owner_object_id=OWNER) == []


def test_owner_key_vault_grant_rejects_a_different_principal() -> None:
    issues = validate(
        role_assignment_change(principal_id="00000000-0000-0000-0000-000000000000"),
        owner_object_id=OWNER,
    )

    assert any("approved owner principal" in issue for issue in issues)


def test_owner_key_vault_grant_rejects_a_broader_role() -> None:
    # Key Vault Administrator — must never be smuggled in via this exemption.
    issues = validate(
        role_assignment_change(role_id="00482a5a-887f-4fb3-b363-3b7fe8e74483"),
        owner_object_id=OWNER,
    )

    assert any("Key Vault Secrets User" in issue for issue in issues)


def test_owner_key_vault_grant_rejects_delete_and_modify() -> None:
    for kind in ("Delete", "Modify"):
        issues = validate(role_assignment_change(kind=kind), owner_object_id=OWNER)
        assert any("must be Create" in issue for issue in issues), kind


def test_owner_key_vault_grant_requires_an_expected_owner() -> None:
    issues = validate(role_assignment_change())

    assert any("expected owner object ID" in issue for issue in issues)


def test_owner_storage_table_reader_create_and_delete_are_allowed() -> None:
    assert (
        validate(storage_role_assignment_change(), owner_object_id=OWNER) == []
    )
    assert (
        validate(
            storage_role_assignment_change(kind="Delete"),
            owner_object_id=OWNER,
        )
        == []
    )


def test_owner_storage_diagnostics_reject_modify() -> None:
    issues = validate(
        storage_role_assignment_change(kind="Modify"),
        owner_object_id=OWNER,
    )

    assert any("must be Create or Delete" in issue for issue in issues)


def test_owner_storage_diagnostics_reject_wrong_principal() -> None:
    issues = validate(
        storage_role_assignment_change(
            principal_id="00000000-0000-0000-0000-000000000000"
        ),
        owner_object_id=OWNER,
    )

    assert any("approved owner principal" in issue for issue in issues)


def test_owner_storage_diagnostics_reject_blob_or_contributor_roles() -> None:
    for role_id in (
        "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1",  # Storage Blob Data Reader
        "0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3",  # Storage Table Data Contributor
    ):
        issues = validate(
            storage_role_assignment_change(role_id=role_id),
            owner_object_id=OWNER,
        )
        assert any("Storage Table Data Reader" in issue for issue in issues)


def test_owner_storage_diagnostics_require_an_exact_role_id() -> None:
    issues = validate(
        storage_role_assignment_change(
            role_id=f"{whatif.STORAGE_TABLE_DATA_READER_ROLE_ID}-broader"
        ),
        owner_object_id=OWNER,
    )

    assert any("Storage Table Data Reader" in issue for issue in issues)


def test_owner_storage_diagnostics_reject_wrong_scope() -> None:
    container_scope = (
        f"{STORAGE_ACCOUNT}/blobServices/default/containers/datasets/"
        "providers/Microsoft.Authorization/roleAssignments/"
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    issues = validate(
        storage_role_assignment_change(resource_id=container_scope),
        owner_object_id=OWNER,
    )

    assert any("scoped directly" in issue for issue in issues)


def test_owner_storage_diagnostics_reject_wrong_account() -> None:
    wrong_account = STORAGE_ROLE_ASSIGNMENT.replace(
        "stirontrailexample",
        "stirontrailother",
    )
    issues = validate(
        storage_role_assignment_change(resource_id=wrong_account),
        owner_object_id=OWNER,
    )

    assert any("approved storage-account scope" in issue for issue in issues)


def test_owner_storage_diagnostics_require_expected_snapshot_and_owner() -> None:
    missing_snapshot = {
        "changeType": "Delete",
        "resourceId": STORAGE_ROLE_ASSIGNMENT,
    }
    issues = validate(missing_snapshot, owner_object_id=OWNER)
    assert any("before properties" in issue for issue in issues)

    issues = validate(storage_role_assignment_change())
    assert any("expected owner object ID" in issue for issue in issues)


def test_stage_c2_whatif_accepts_only_google_rollout_changes() -> None:
    result = validate(
        change(
            "Modify",
            CONTAINER_APP,
            ("properties.configuration.secrets", "Array"),
            ("properties.runningStatus", "Delete"),
            ("properties.template.containers", "Array"),
            ("properties.template.revisionSuffix", "Modify"),
        ),
        change(
            "Modify",
            AUTH_CONFIG,
            (
                "properties.identityProviders.azureActiveDirectory.isAutoProvisioned",
                "Delete",
            ),
            ("properties.identityProviders.google", "Create"),
        ),
        change("Create", GOOGLE_SECRET),
        change("Create", BETA_REVEAL_SECRET),
    )

    assert result == []


def test_stage_c2_whatif_rejects_non_google_resource_mutation() -> None:
    result = validate(
        change(
            "Modify",
            CONTAINER_APP,
            ("properties.configuration.secrets", "Array"),
            ("properties.template.containers", "Array"),
            ("properties.template.revisionSuffix", "Modify"),
        ),
        change("Modify", AUTH_CONFIG, ("properties.identityProviders.google", "Create")),
        change("Create", GOOGLE_SECRET),
        change("Create", BETA_REVEAL_SECRET),
        change(
            "Modify",
            f"{PREFIX}Microsoft.Storage/storageAccounts/stirontrail-example",
        ),
    )

    assert len(result) == 1
    assert "forbidden" in result[0]


def test_stage_c2_whatif_rejects_unapproved_container_app_property() -> None:
    result = validate(
        change(
            "Modify",
            CONTAINER_APP,
            ("properties.configuration.secrets", "Array"),
            ("properties.template.containers", "Array"),
            ("properties.template.revisionSuffix", "Modify"),
            ("properties.configuration.ingress.traffic", "Modify"),
        ),
        change("Modify", AUTH_CONFIG, ("properties.identityProviders.google", "Create")),
        change("Create", GOOGLE_SECRET),
        change("Create", BETA_REVEAL_SECRET),
    )

    assert len(result) == 1
    assert "unapproved property delta" in result[0]


def test_stage_c2_whatif_accepts_capacity_only_update() -> None:
    result = validate(
        change(
            "Modify",
            CONTAINER_APP,
            ("properties.template.containers", "Array"),
            ("properties.template.revisionSuffix", "Modify"),
        ),
        change(
            "Modify",
            AUTH_CONFIG,
            (
                "properties.identityProviders.azureActiveDirectory.isAutoProvisioned",
                "Delete",
            ),
        ),
        change("NoChange", BETA_REVEAL_SECRET),
    )

    assert result == []


def test_stage_c2_whatif_accepts_idempotent_container_reconciliation() -> None:
    result = validate(
        change(
            "Modify",
            CONTAINER_APP,
            ("properties.template.containers", "Array"),
        ),
        change(
            "Modify",
            AUTH_CONFIG,
            (
                "properties.identityProviders.azureActiveDirectory.isAutoProvisioned",
                "Delete",
            ),
        ),
        change("NoChange", BETA_REVEAL_SECRET),
    )

    assert result == []


def test_google_provider_change_still_requires_revision_update() -> None:
    result = validate(
        change(
            "Modify",
            CONTAINER_APP,
            ("properties.configuration.secrets", "Array"),
            ("properties.template.containers", "Array"),
        ),
        change("Modify", AUTH_CONFIG, ("properties.identityProviders.google", "Delete")),
        change("NoChange", BETA_REVEAL_SECRET),
    )

    assert any("revision update" in issue for issue in result)


def test_stage_c2_whatif_accepts_google_removal_without_secret_deletion() -> None:
    result = validate(
        change(
            "Modify",
            CONTAINER_APP,
            ("properties.configuration.secrets", "Array"),
            ("properties.template.containers", "Array"),
            ("properties.template.revisionSuffix", "Modify"),
        ),
        change("Modify", AUTH_CONFIG, ("properties.identityProviders.google", "Delete")),
        change("NoChange", BETA_REVEAL_SECRET),
    )

    assert result == []


def test_stage_c2_whatif_accepts_safe_no_op() -> None:
    assert validate(change("Ignore", CONTAINER_APP)) == []


def test_stage_c2_whatif_accepts_existing_google_secret_on_retry() -> None:
    result = validate(
        change(
            "Modify",
            CONTAINER_APP,
            ("properties.configuration.secrets", "Array"),
            ("properties.template.containers", "Array"),
            ("properties.template.revisionSuffix", "Modify"),
        ),
        change("Modify", AUTH_CONFIG, ("properties.identityProviders.google", "Create")),
        change("NoChange", GOOGLE_SECRET),
        change("NoChange", BETA_REVEAL_SECRET),
    )

    assert result == []
