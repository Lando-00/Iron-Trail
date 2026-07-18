"""Fail closed when an Azure what-if exceeds the Stage C resource allowlist."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ALLOWED_CREATE_TYPES = {
    "microsoft.app/containerapps",
    "microsoft.app/containerapps/authconfigs",
    "microsoft.app/managedenvironments",
    "microsoft.authorization/roleassignments",
    "microsoft.consumption/budgets",
    "microsoft.containerregistry/registries",
    "microsoft.insights/components",
    "microsoft.keyvault/vaults",
    "microsoft.keyvault/vaults/secrets",
    "microsoft.managedidentity/userassignedidentities",
    "microsoft.operationalinsights/workspaces",
    "microsoft.storage/storageaccounts",
    "microsoft.storage/storageaccounts/blobservices",
    "microsoft.storage/storageaccounts/blobservices/containers",
    "microsoft.storage/storageaccounts/managementpolicies",
    "microsoft.storage/storageaccounts/tableservices",
    "microsoft.storage/storageaccounts/tableservices/tables",
}
ROLE_IDS = {
    "acr_pull": "7f951dda-4ed3-4680-a7ca-43fe172d538d",
    "blob_contributor": "ba92f5b4-2d11-453d-a403-e96b0029c9fe",
    "table_contributor": "0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3",
    "key_vault_secrets_user": "4633458b-17de-408a-b874-0445c86b69e6",
    "foundry_user": "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd",
}


def resource_type(resource_id: str) -> str:
    parts = [part for part in resource_id.strip("/").split("/") if part]
    provider_indexes = [
        index for index, part in enumerate(parts) if part.lower() == "providers"
    ]
    if not provider_indexes:
        return ""
    provider_parts = parts[provider_indexes[-1] + 1 :]
    if len(provider_parts) < 2:
        return ""
    return "/".join([provider_parts[0], *provider_parts[1::2]]).lower()


def allowed_roles_for_parent(parent: str, foundry_id: str) -> set[str] | None:
    if parent == foundry_id:
        return {ROLE_IDS["foundry_user"]}
    if "/providers/microsoft.containerregistry/registries/crirontrail" in parent:
        return {ROLE_IDS["acr_pull"]}
    if "/providers/microsoft.storage/storageaccounts/stirontrail" in parent:
        return {
            ROLE_IDS["blob_contributor"],
            ROLE_IDS["table_contributor"],
        }
    if "/providers/microsoft.keyvault/vaults/kv-irontrail-" in parent:
        return {ROLE_IDS["key_vault_secrets_user"]}
    return None


def validate_symbolic_role_assignment(
    resource_id: str,
    *,
    subscription_id: str,
    resource_group: str,
    foundry_id: str,
) -> list[str]:
    lowered = resource_id.lower()
    scope_match = re.search(r"extensionresourceid\('([^']+)'", lowered)
    role_matches = re.findall(r"/roledefinitions/([0-9a-f-]{36})", lowered)
    identity_match = re.search(
        r"reference\('([^']+/providers/microsoft\.managedidentity/"
        r"userassignedidentities/id-irontrail-[^']+)'",
        lowered,
    )
    if (
        not scope_match
        or len(role_matches) != 1
        or not identity_match
        or "'microsoft.authorization/roleassignments'" not in lowered
    ):
        return [f"Unsupported resource expression is not approved: {resource_id}."]

    parent = scope_match.group(1).rstrip("/")
    expected_identity_prefix = (
        f"/subscriptions/{subscription_id}/resourcegroups/{resource_group}/providers/"
        "microsoft.managedidentity/userassignedidentities/id-irontrail-"
    ).lower()
    if not identity_match.group(1).startswith(expected_identity_prefix):
        return [f"Role assignment identity is not approved: {resource_id}."]
    allowed_roles = allowed_roles_for_parent(parent, foundry_id)
    if allowed_roles is None:
        return [f"Role assignment scope is not approved: {resource_id}."]
    if role_matches[0] not in allowed_roles:
        return [f"Role definition is not approved: {resource_id}."]
    return []


def validate_whatif(
    payload: dict[str, Any],
    *,
    subscription_id: str,
    resource_group: str,
    foundry_account: str,
) -> list[str]:
    properties = payload.get("properties")
    if isinstance(properties, dict) and "changes" in properties:
        changes = properties["changes"]
    elif "changes" in payload:
        changes = payload["changes"]
    else:
        return ["What-if payload is missing the changes field."]
    if not isinstance(changes, list):
        return ["What-if payload does not contain a changes list."]

    rg_prefix = (
        f"/subscriptions/{subscription_id}/resourcegroups/{resource_group}/"
    ).lower()
    foundry_id = (
        f"{rg_prefix}providers/microsoft.cognitiveservices/accounts/"
        f"{foundry_account}"
    )
    issues: list[str] = []
    for change in changes:
        if not isinstance(change, dict):
            issues.append("What-if contains a non-object change.")
            continue
        change_type = str(change.get("changeType", "")).lower()
        resource_id = str(change.get("resourceId", ""))
        lowered_id = resource_id.lower()
        if change_type in {"nochange", "ignore"}:
            continue
        if change_type == "unsupported":
            issues.extend(
                validate_symbolic_role_assignment(
                    resource_id,
                    subscription_id=subscription_id,
                    resource_group=resource_group,
                    foundry_id=foundry_id,
                )
            )
            continue
        if change_type != "create":
            issues.append(f"{change_type or 'unknown'} is forbidden for {resource_id}.")
            continue
        if not lowered_id.startswith(rg_prefix):
            issues.append(f"Create is outside rg-IronTrail: {resource_id}.")
            continue

        kind = resource_type(resource_id)
        if kind not in ALLOWED_CREATE_TYPES:
            issues.append(f"Resource type is not approved: {kind or resource_id}.")
            continue
        if kind == "microsoft.authorization/roleassignments":
            role_marker = "/providers/microsoft.authorization/roleassignments/"
            parent = lowered_id.split(role_marker, 1)[0]
            allowed_roles = allowed_roles_for_parent(parent, foundry_id)
            if allowed_roles is None:
                issues.append(f"Role assignment scope is not approved: {resource_id}.")
                continue

            after = change.get("after")
            role_properties = after.get("properties") if isinstance(after, dict) else None
            if not isinstance(role_properties, dict):
                issues.append(f"Role assignment details are missing: {resource_id}.")
                continue
            role_definition = str(role_properties.get("roleDefinitionId", "")).lower()
            approved_role_definitions = {
                (
                    f"/subscriptions/{subscription_id}/providers/"
                    f"microsoft.authorization/roledefinitions/{role_id}"
                ).lower()
                for role_id in allowed_roles
            }
            if role_definition.rstrip("/") not in approved_role_definitions:
                issues.append(f"Role definition is not approved: {resource_id}.")
            if role_properties.get("principalType") != "ServicePrincipal":
                issues.append(f"Role principal type is not approved: {resource_id}.")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("whatif", type=Path)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--resource-group", default="rg-IronTrail")
    parser.add_argument("--foundry-account", default="irontrail-resource")
    args = parser.parse_args()

    payload = json.loads(args.whatif.read_text(encoding="utf-8"))
    issues = validate_whatif(
        payload,
        subscription_id=args.subscription_id,
        resource_group=args.resource_group,
        foundry_account=args.foundry_account,
    )
    print(json.dumps({"ok": not issues, "issues": issues}, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
