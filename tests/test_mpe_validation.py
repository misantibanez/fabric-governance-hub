import unittest

from mpe_validation import MpeValidationError, mpe_audit_record, validate_mpe_configuration


KEY_VAULT_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/governance/providers/Microsoft.KeyVault/vaults/governance-kv"
)
COGNITIVE_SERVICES_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/governance/providers/Microsoft.CognitiveServices/accounts/governance-ai"
)


class FakeResponse:
    def __init__(self, status_code, resource_type=None, group_ids=None):
        self.status_code = status_code
        self.resource_type = resource_type
        self.group_ids = group_ids

    def json(self):
        if self.group_ids is not None:
            return {"value": [{"properties": {"groupId": value}} for value in self.group_ids]}
        return {"type": self.resource_type} if self.resource_type else {}


class ArmResourceLookup:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url, headers, params, timeout):
        self.calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return self.responses[url]


class MpeValidationTests(unittest.TestCase):
    def test_requires_key_vault_setting(self):
        with self.assertRaisesRegex(MpeValidationError, "mpe_keyvault_resource_id.*required"):
            validate_mpe_configuration({}, False, {}, ArmResourceLookup({}))

    def test_requires_selected_cognitive_services_setting(self):
        lookup = ArmResourceLookup({
            f"https://management.azure.com{KEY_VAULT_ID}": FakeResponse(
                200, "Microsoft.KeyVault/vaults"
            ),
            f"https://management.azure.com{KEY_VAULT_ID}/privateLinkResources": FakeResponse(
                200, group_ids=["vault"]
            ),
        })

        with self.assertRaisesRegex(
            MpeValidationError, "mpe_cognitive_services_resource_id.*required"
        ):
            validate_mpe_configuration(
                {"mpe_keyvault_resource_id": KEY_VAULT_ID}, True, {}, lookup
            )

    def test_rejects_malformed_and_wrong_resource_types_before_arm_lookup(self):
        lookup = ArmResourceLookup({})

        with self.assertRaises(MpeValidationError) as context:
            validate_mpe_configuration(
                {
                    "mpe_keyvault_resource_id": "not-an-id",
                    "mpe_cognitive_services_resource_id": KEY_VAULT_ID,
                },
                True,
                {},
                lookup,
            )

        self.assertIn("complete Azure resource ID", str(context.exception))
        self.assertIn("expected Microsoft.CognitiveServices/accounts", str(context.exception))
        self.assertEqual([], lookup.calls)

    def test_reports_missing_and_forbidden_arm_resources(self):
        lookup = ArmResourceLookup({
            f"https://management.azure.com{KEY_VAULT_ID}": FakeResponse(404),
            f"https://management.azure.com{COGNITIVE_SERVICES_ID}": FakeResponse(403),
        })

        with self.assertRaises(MpeValidationError) as context:
            validate_mpe_configuration(
                {
                    "mpe_keyvault_resource_id": KEY_VAULT_ID,
                    "mpe_cognitive_services_resource_id": COGNITIVE_SERVICES_ID,
                },
                True,
                {},
                lookup,
            )

        self.assertIn("does not exist", str(context.exception))
        self.assertIn("Azure permissions", str(context.exception))

    def test_returns_immutable_targets_and_audit_record(self):
        lookup = ArmResourceLookup({
            f"https://management.azure.com{KEY_VAULT_ID}": FakeResponse(
                200, "Microsoft.KeyVault/vaults"
            ),
            f"https://management.azure.com{KEY_VAULT_ID}/privateLinkResources": FakeResponse(
                200, group_ids=["vault"]
            ),
            f"https://management.azure.com{COGNITIVE_SERVICES_ID}": FakeResponse(
                200, "Microsoft.CognitiveServices/accounts"
            ),
            f"https://management.azure.com{COGNITIVE_SERVICES_ID}/privateLinkResources": FakeResponse(
                200, group_ids=["account"]
            ),
        })

        targets = validate_mpe_configuration(
            {
                "mpe_keyvault_resource_id": f"{KEY_VAULT_ID}/",
                "mpe_cognitive_services_resource_id": COGNITIVE_SERVICES_ID,
            },
            True,
            {"Authorization": "Bearer hidden"},
            lookup,
        )

        self.assertIsInstance(targets, tuple)
        self.assertEqual(["vault", "account"], [target.subresource_type for target in targets])
        self.assertEqual(KEY_VAULT_ID, targets[0].resource_id)
        self.assertNotIn("Authorization", str(mpe_audit_record(targets)))
        self.assertEqual(15, lookup.calls[0]["timeout"])

    def test_rejects_resource_without_required_private_link_subresource(self):
        lookup = ArmResourceLookup({
            f"https://management.azure.com{KEY_VAULT_ID}": FakeResponse(
                200, "Microsoft.KeyVault/vaults"
            ),
            f"https://management.azure.com{KEY_VAULT_ID}/privateLinkResources": FakeResponse(
                200, group_ids=["other"]
            ),
        })

        with self.assertRaisesRegex(MpeValidationError, "private-link subresource `vault`"):
            validate_mpe_configuration(
                {"mpe_keyvault_resource_id": KEY_VAULT_ID}, False, {}, lookup
            )


if __name__ == "__main__":
    unittest.main()