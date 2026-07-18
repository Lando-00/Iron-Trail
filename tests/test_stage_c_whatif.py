from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_stage_c_whatif.py"
SPEC = importlib.util.spec_from_file_location("validate_stage_c_whatif", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
whatif = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = whatif
SPEC.loader.exec_module(whatif)

SUBSCRIPTION = "sub"
RESOURCE_GROUP = "rg-IronTrail"
FOUNDRY = "irontrail-resource"


def payload(*changes):
    return {"properties": {"changes": list(changes)}}


def change(kind: str, resource_id: str, *, after=None):
    value = {"changeType": kind, "resourceId": resource_id}
    if after is not None:
        value["after"] = after
    return value


def role_after(role_id: str, *, subscription_id: str = SUBSCRIPTION):
    return {
        "properties": {
            "principalId": "known-after-deployment",
            "principalType": "ServicePrincipal",
            "roleDefinitionId": (
                f"/subscriptions/{subscription_id}/providers/"
                f"Microsoft.Authorization/roleDefinitions/{role_id}"
            ),
        }
    }


def rg_resource(path: str) -> str:
    return f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}/{path}"


def validate(value):
    return whatif.validate_whatif(
        value,
        subscription_id=SUBSCRIPTION,
        resource_group=RESOURCE_GROUP,
        foundry_account=FOUNDRY,
    )


def test_stage_c_whatif_accepts_expected_creates() -> None:
    result = validate(
        payload(
            change(
                "Create",
                rg_resource(
                    "providers/Microsoft.Storage/storageAccounts/stirontrailabc123"
                ),
            ),
            change(
                "Create",
                rg_resource(
                    "providers/Microsoft.CognitiveServices/accounts/"
                    f"{FOUNDRY}/providers/Microsoft.Authorization/roleAssignments/role"
                ),
                after=role_after(whatif.ROLE_IDS["foundry_user"]),
            ),
        )
    )

    assert result == []


def test_stage_c_whatif_rejects_delete_and_foundry_modify() -> None:
    foundry_id = rg_resource(
        f"providers/Microsoft.CognitiveServices/accounts/{FOUNDRY}"
    )

    result = validate(
        payload(
            change("Delete", rg_resource("providers/Microsoft.Storage/storageAccounts/a")),
            change("Modify", foundry_id),
        )
    )

    assert len(result) == 2
    assert all("forbidden" in issue for issue in result)


def test_stage_c_whatif_rejects_unapproved_role_scope() -> None:
    result = validate(
        payload(
            change(
                "Create",
                rg_resource("providers/Microsoft.Authorization/roleAssignments/role"),
                after=role_after(whatif.ROLE_IDS["foundry_user"]),
            )
        )
    )

    assert result == [
        "Role assignment scope is not approved: "
        "/subscriptions/sub/resourceGroups/rg-IronTrail/providers/"
        "Microsoft.Authorization/roleAssignments/role."
    ]


def test_stage_c_whatif_rejects_unapproved_role_definition() -> None:
    result = validate(
        payload(
            change(
                "Create",
                rg_resource(
                    "providers/Microsoft.CognitiveServices/accounts/"
                    f"{FOUNDRY}/providers/Microsoft.Authorization/roleAssignments/role"
                ),
                after=role_after("8e3af657-a8ff-443c-a75c-2fe8c4bcb635"),
            )
        )
    )

    assert len(result) == 1
    assert "Role definition is not approved" in result[0]


def test_stage_c_whatif_rejects_foreign_subscription_role_definition() -> None:
    result = validate(
        payload(
            change(
                "Create",
                rg_resource(
                    "providers/Microsoft.CognitiveServices/accounts/"
                    f"{FOUNDRY}/providers/Microsoft.Authorization/roleAssignments/role"
                ),
                after=role_after(
                    whatif.ROLE_IDS["foundry_user"],
                    subscription_id="foreign-subscription",
                ),
            )
        )
    )

    assert len(result) == 1
    assert "Role definition is not approved" in result[0]


def test_stage_c_whatif_rejects_missing_changes() -> None:
    assert validate({"properties": {}}) == [
        "What-if payload is missing the changes field."
    ]
