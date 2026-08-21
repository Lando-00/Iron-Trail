"""Fail closed when a Stage C2 what-if exceeds the Google rollout allowlist."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

KEY_VAULT_SECRETS_USER_ROLE_ID = "4633458b-17de-408a-b874-0445c86b69e6"
STORAGE_TABLE_DATA_READER_ROLE_ID = "76199698-9eea-4c19-bc75-cec21354c6b6"


def _changes(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [change for change in payload if isinstance(change, dict)]
    if not isinstance(payload, dict):
        return []

    properties = payload.get("properties")
    if isinstance(properties, dict) and isinstance(properties.get("changes"), list):
        return [change for change in properties["changes"] if isinstance(change, dict)]
    if isinstance(payload.get("changes"), list):
        return [change for change in payload["changes"] if isinstance(change, dict)]
    return []


def _delta_pairs(change: dict[str, Any]) -> set[tuple[str, str]]:
    deltas = change.get("delta")
    if not isinstance(deltas, list):
        return set()

    return {
        (str(delta.get("path", "")), str(delta.get("propertyChangeType", "")))
        for delta in deltas
        if isinstance(delta, dict)
    }


def _role_id(role_definition: Any) -> str:
    return str(role_definition or "").rstrip("/").rsplit("/", maxsplit=1)[-1].lower()


def validate_stage_c2_whatif(
    payload: Any,
    *,
    subscription_id: str,
    resource_group: str,
    owner_object_id: str | None = None,
    storage_account_name: str | None = None,
) -> list[str]:
    changes = _changes(payload)
    if not changes:
        return ["What-if payload is missing a changes list."]

    resource_prefix = (
        f"/subscriptions/{subscription_id}/resourcegroups/{resource_group}/providers/"
    ).lower()
    container_app_id = f"{resource_prefix}microsoft.app/containerapps/ca-irontrail-"
    key_vault_secret_id = (
        f"{resource_prefix}microsoft.keyvault/vaults/kv-irontrail-"
    )
    storage_accounts_id = f"{resource_prefix}microsoft.storage/storageaccounts/"
    role_assignment_marker = "/providers/microsoft.authorization/roleassignments/"
    allowed_container_deltas = {
        ("properties.configuration.secrets", "Array"),
        ("properties.runningStatus", "Delete"),
        ("properties.template.containers", "Array"),
        ("properties.template.revisionSuffix", "Modify"),
    }
    required_container_deltas = {
        ("properties.template.containers", "Array"),
    }
    allowed_auth_deltas = {
        (
            "properties.identityProviders.azureActiveDirectory.isAutoProvisioned",
            "Delete",
        ),
        ("properties.identityProviders.google", "Create"),
        ("properties.identityProviders.google", "Delete"),
    }

    saw_container_app = False
    saw_container_secret_delta = False
    saw_auth_config = False
    saw_google_secret = False
    saw_beta_reveal_secret = False
    saw_google_provider_create = False
    saw_google_provider_change = False
    saw_revision_suffix_delta = False
    issues: list[str] = []

    for change in changes:
        change_type = str(change.get("changeType", "")).lower()
        resource_id = str(change.get("resourceId", ""))
        lowered_id = resource_id.lower()

        is_container_app = (
            lowered_id.startswith(container_app_id)
            and "/authconfigs/" not in lowered_id
        )
        is_auth_config = (
            lowered_id.startswith(container_app_id)
            and lowered_id.endswith("/authconfigs/current")
        )
        is_google_secret = (
            lowered_id.startswith(key_vault_secret_id)
            and lowered_id.endswith("/secrets/google-client-secret")
        )
        is_beta_reveal_secret = (
            lowered_id.startswith(key_vault_secret_id)
            and lowered_id.endswith("/secrets/beta-reveal-seed")
        )
        is_key_vault_role_assignment = (
            lowered_id.startswith(key_vault_secret_id)
            and role_assignment_marker in lowered_id
        )
        storage_scope = lowered_id.partition(role_assignment_marker)[0]
        storage_name = storage_scope.removeprefix(storage_accounts_id)
        is_storage_role_assignment = (
            role_assignment_marker in lowered_id
            and storage_scope.startswith(storage_accounts_id)
        )

        if change_type in {"ignore", "nochange"}:
            if is_google_secret:
                saw_google_secret = True
            if is_beta_reveal_secret:
                saw_beta_reveal_secret = True
            continue

        if is_container_app:
            saw_container_app = True
            if change_type != "modify":
                issues.append(
                    f"Container App change must be Modify, found {change_type or 'unknown'}."
                )
                continue

            actual_deltas = _delta_pairs(change)
            unexpected_deltas = actual_deltas - allowed_container_deltas
            missing_deltas = required_container_deltas - actual_deltas
            saw_container_secret_delta = (
                saw_container_secret_delta
                or ("properties.configuration.secrets", "Array") in actual_deltas
            )
            saw_revision_suffix_delta = (
                saw_revision_suffix_delta
                or ("properties.template.revisionSuffix", "Modify") in actual_deltas
            )
            if unexpected_deltas:
                issues.append(
                    "Container App contains an unapproved property delta: "
                    + ", ".join(path for path, _ in sorted(unexpected_deltas))
                    + "."
                )
            if missing_deltas:
                issues.append(
                    "Container App is missing an expected Stage C2 delta: "
                    + ", ".join(path for path, _ in sorted(missing_deltas))
                    + "."
                )
            continue

        if is_auth_config:
            saw_auth_config = True
            if change_type != "modify":
                issues.append(
                    f"Auth config change must be Modify, found {change_type or 'unknown'}."
                )
                continue

            actual_deltas = _delta_pairs(change)
            unexpected_deltas = actual_deltas - allowed_auth_deltas
            if unexpected_deltas:
                issues.append(
                    "Auth config contains an unapproved property delta: "
                    + ", ".join(path for path, _ in sorted(unexpected_deltas))
                    + "."
                )
            saw_google_provider_create = (
                saw_google_provider_create
                or ("properties.identityProviders.google", "Create") in actual_deltas
            )
            google_provider_deltas = {
                ("properties.identityProviders.google", "Create"),
                ("properties.identityProviders.google", "Delete"),
            }.intersection(actual_deltas)
            saw_google_provider_change = (
                saw_google_provider_change or bool(google_provider_deltas)
            )
            aad_metadata_only = actual_deltas <= {
                (
                    "properties.identityProviders.azureActiveDirectory.isAutoProvisioned",
                    "Delete",
                )
            }
            if not google_provider_deltas and not aad_metadata_only:
                issues.append("Auth config is missing an approved Google provider change.")
            continue

        if is_google_secret:
            saw_google_secret = True
            if change_type not in {"create", "modify"}:
                issues.append(
                    "Google Key Vault secret must be Create or Modify, found "
                    f"{change_type or 'unknown'}."
                )
            continue

        if is_beta_reveal_secret:
            saw_beta_reveal_secret = True
            if change_type not in {"create", "modify"}:
                issues.append(
                    "Beta reveal-seed Key Vault secret must be Create or Modify, found "
                    f"{change_type or 'unknown'}."
                )
            continue

        if is_key_vault_role_assignment:
            # Only the declared owner break-glass grant is permitted, and only
            # as a Create. Both the role and the principal are pinned so this
            # exemption cannot be widened into arbitrary RBAC changes.
            if change_type != "create":
                issues.append(
                    "Key Vault role assignment must be Create, found "
                    f"{change_type or 'unknown'}."
                )
                continue
            after = change.get("after")
            properties = after.get("properties") if isinstance(after, dict) else None
            properties = properties if isinstance(properties, dict) else {}
            role_definition = _role_id(properties.get("roleDefinitionId"))
            principal_id = str(properties.get("principalId", "")).strip().lower()
            if role_definition != KEY_VAULT_SECRETS_USER_ROLE_ID:
                issues.append(
                    "Key Vault role assignment must grant Key Vault Secrets User."
                )
            if not owner_object_id:
                issues.append(
                    "Key Vault role assignment requires an expected owner object ID."
                )
            elif principal_id != owner_object_id.strip().lower():
                issues.append(
                    "Key Vault role assignment must target the approved owner principal."
                )
            continue

        if is_storage_role_assignment:
            # The owner may temporarily read Table metadata for diagnostics.
            # Create and Delete are both required for the explicit
            # enable-audit-disable workflow; the principal, role, and
            # storage-account scope remain pinned in either direction.
            expected_storage_name = (storage_account_name or "").strip().lower()
            if not expected_storage_name:
                issues.append(
                    "Storage diagnostic role assignment requires an expected "
                    "storage account name."
                )
            elif storage_name != expected_storage_name:
                issues.append(
                    "Storage diagnostic role assignment must use the approved "
                    "storage-account scope."
                )
            if "/" in storage_name:
                issues.append(
                    "Storage diagnostic role assignment must be scoped directly "
                    "to the storage account."
                )
            if change_type not in {"create", "delete"}:
                issues.append(
                    "Storage diagnostic role assignment must be Create or Delete, "
                    f"found {change_type or 'unknown'}."
                )
                continue
            snapshot_name = "after" if change_type == "create" else "before"
            snapshot = change.get(snapshot_name)
            properties = snapshot.get("properties") if isinstance(snapshot, dict) else None
            if not isinstance(properties, dict):
                issues.append(
                    "Storage diagnostic role assignment is missing its "
                    f"{snapshot_name} properties."
                )
                continue
            role_definition = _role_id(properties.get("roleDefinitionId"))
            principal_id = str(properties.get("principalId", "")).strip().lower()
            if role_definition != STORAGE_TABLE_DATA_READER_ROLE_ID:
                issues.append(
                    "Storage diagnostic role assignment must grant "
                    "Storage Table Data Reader."
                )
            if not owner_object_id:
                issues.append(
                    "Storage diagnostic role assignment requires an expected "
                    "owner object ID."
                )
            elif principal_id != owner_object_id.strip().lower():
                issues.append(
                    "Storage diagnostic role assignment must target the approved "
                    "owner principal."
                )
            continue

        issues.append(
            f"{change_type or 'unknown'} is forbidden for {resource_id or 'an unnamed resource'}."
        )

    if (saw_auth_config or saw_google_secret) and not saw_container_app:
        issues.append("Google provider or secret changes require a Container App update.")
    if saw_container_secret_delta and not saw_auth_config:
        issues.append("Container App secret changes require an auth config update.")
    if saw_container_secret_delta and not saw_beta_reveal_secret:
        issues.append(
            "Container App secret changes require the beta reveal-seed Key Vault secret."
        )
    if saw_google_provider_create and not saw_google_secret:
        issues.append("Adding Google authentication requires the Google Key Vault secret.")
    if saw_google_provider_change and not saw_revision_suffix_delta:
        issues.append("Google provider changes require a Container App revision update.")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("whatif", type=Path)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--resource-group", default="rg-IronTrail")
    parser.add_argument(
        "--owner-object-id",
        help="Entra object ID permitted to receive the Key Vault break-glass grant.",
    )
    parser.add_argument(
        "--storage-account-name",
        help="Storage account permitted to receive the temporary diagnostic grant.",
    )
    args = parser.parse_args()

    payload = json.loads(args.whatif.read_text(encoding="utf-8"))
    issues = validate_stage_c2_whatif(
        payload,
        subscription_id=args.subscription_id,
        resource_group=args.resource_group,
        owner_object_id=args.owner_object_id,
        storage_account_name=args.storage_account_name,
    )
    print(json.dumps({"ok": not issues, "issues": issues}, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
