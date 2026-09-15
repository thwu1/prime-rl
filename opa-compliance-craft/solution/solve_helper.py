#!/usr/bin/env python3
"""
Generate /app/tenant_input.json that satisfies the CISA ScubaGear AAD
Rego policy targets defined in /app/target_outcomes.json.

Target outcomes (20 policies):
  PASS: 1.1, 2.1, 2.3, 3.2, 3.3, 3.4, 3.5, 3.8, 3.9,
        5.1, 5.2, 5.3, 6.1, 7.1, 7.3, 8.1, 8.2
  FAIL: 3.1 (no phishing-resistant MFA),
        3.7 (no managed device auth),
        7.2 (least-privilege ratio too high)

Key design constraints:
- 3.1 FAIL: No CA policy uses phishing-resistant authentication strength
- 3.2 PASS: A CA policy uses "mfa" built-in control (general MFA)
- 3.3 PASS: Since 3.1 fails AND MS Authenticator is enabled,
            MS Auth must be properly configured (app info + location for all_users)
- 3.7 FAIL: No CA policy with compliantDevice+domainJoinedDevice+count=2+Operator=OR
- 3.8 PASS: A CA policy requires managed device for MFA registration
            (IncludeUserActions with urn:user:registersecurityinfo)
- 7.1 PASS: 2-8 global admins (we use 3)
- 7.2 FAIL: GlobalAdmins(3) > NotGlobalAdmins(2) => ratio > 1
- 2.1/2.3: Require AAD_PREMIUM_P2 in service_plans
"""

import json

INT_MAX = 2147483647

# Restricted access GUID for guest user role
RESTRICTED_ACCESS = "2af84b1e-32c8-42b7-82bc-daa82404023b"


def make_ca_policy(display_name, extra_conditions=None, grant_controls=None,
                   include_apps=True, include_user_actions=None):
    """Build a conditional access policy with standard fields."""
    conditions = {
        "Users": {
            "IncludeUsers": ["All"],
            "ExcludeUsers": [],
            "ExcludeRoles": [],
            "ExcludeGroups": [],
            "ExcludeGuestsOrExternalUsers": None,
        },
        "Applications": {
            "IncludeApplications": ["All"] if include_apps else [],
            "ExcludeApplications": [],
        },
    }
    if include_user_actions:
        conditions["Applications"]["IncludeUserActions"] = include_user_actions
    if extra_conditions:
        conditions.update(extra_conditions)
    policy = {
        "DisplayName": display_name,
        "State": "enabled",
        "Conditions": conditions,
        "GrantControls": grant_controls or {"BuiltInControls": []},
    }
    return policy


tenant_config = {
    # =========================================================================
    # Conditional Access Policies
    # =========================================================================
    "conditional_access_policies": [
        # MS.AAD.1.1v1 — Block legacy authentication
        make_ca_policy(
            "Block Legacy Authentication",
            extra_conditions={
                "ClientAppTypes": ["other", "exchangeActiveSync"],
            },
            grant_controls={"BuiltInControls": ["block"]},
        ),

        # MS.AAD.2.1v1 — Block high-risk users
        make_ca_policy(
            "Block High Risk Users",
            extra_conditions={
                "UserRiskLevels": ["high"],
            },
            grant_controls={"BuiltInControls": ["block"]},
        ),

        # MS.AAD.2.3v1 — Block high-risk sign-ins
        make_ca_policy(
            "Block High Risk Sign-Ins",
            extra_conditions={
                "SignInRiskLevels": ["high"],
            },
            grant_controls={"BuiltInControls": ["block"]},
        ),

        # MS.AAD.3.2v2 — Require general MFA for all users
        # Uses "mfa" built-in control, NOT phishing-resistant auth strength.
        # This satisfies 3.2 (general MFA) while leaving 3.1 (phishing-resistant) failing.
        make_ca_policy(
            "Require MFA for All Users",
            grant_controls={"BuiltInControls": ["mfa"]},
        ),

        # NO policy for MS.AAD.3.1v1 — intentionally absent (phishing-resistant MFA)
        # NO policy for MS.AAD.3.7v1 — intentionally absent (managed device auth)

        # MS.AAD.3.8v1 — Require managed device for MFA registration
        # Uses IncludeUserActions instead of IncludeApplications.
        # At least one of compliantDevice/domainJoinedDevice must be in BuiltInControls.
        make_ca_policy(
            "Require Managed Device for MFA Registration",
            include_apps=False,
            include_user_actions=["urn:user:registersecurityinfo"],
            grant_controls={"BuiltInControls": ["compliantDevice"]},
        ),

        # MS.AAD.3.9v1 — Block device code flow
        make_ca_policy(
            "Block Device Code Flow",
            extra_conditions={
                "AuthenticationFlows": {"TransferMethods": "deviceCodeFlow"},
            },
            grant_controls={"BuiltInControls": ["block"]},
        ),
    ],

    # =========================================================================
    # Service Plans — AAD P2 license required for 2.1v1, 2.3v1
    # =========================================================================
    "service_plans": [
        {
            "ServicePlanId": "eec0eb4f-6444-4f95-aba0-50c24d67f998",
            "ServicePlanName": "AAD_PREMIUM_P2",
        },
    ],

    # =========================================================================
    # Authentication Methods — for 3.3v2, 3.4v1, 3.5v2
    # =========================================================================
    "authentication_method": [
        {
            "authentication_method_feature_settings": [
                # MS Authenticator — enabled and properly configured.
                # Since 3.1 fails (no phishing-resistant MFA) and MS Auth is enabled,
                # the 3.3 standard-path check fires and requires proper configuration.
                {
                    "Id": "MicrosoftAuthenticator",
                    "State": "enabled",
                    "IsSoftwareOathEnabled": False,
                    "FeatureSettings": {
                        "DisplayAppInformationRequiredState": {
                            "State": "enabled",
                            "IncludeTarget": {"Id": "all_users"},
                        },
                        "DisplayLocationInformationRequiredState": {
                            "State": "enabled",
                            "IncludeTarget": {"Id": "all_users"},
                        },
                    },
                },
                # Low-security auth methods — all disabled for 3.5v2
                {"Id": "Sms", "State": "disabled"},
                {"Id": "Voice", "State": "disabled"},
                {"Id": "Email", "State": "disabled"},
            ],
            # Migration state — migrationComplete for 3.4v1
            "authentication_method_policy": {
                "PolicyMigrationState": "migrationComplete",
            },
        },
    ],

    # =========================================================================
    # Authorization Policies — for 5.1v1, 5.2v1, 8.1v1, 8.2v1
    # =========================================================================
    "authorization_policies": [
        {
            "Id": "authorizationPolicy",
            "DefaultUserRolePermissions": {
                # Only admins can register apps (5.1 pass)
                "AllowedToCreateApps": False,
            },
            # Empty = no risky consent policies (5.2 pass)
            "PermissionGrantPolicyIdsAssignedToDefaultUserRole": [],
            # Restricted access for guests (8.1 pass)
            "GuestUserRoleId": RESTRICTED_ACCESS,
            # Only admins and guest inviters can invite (8.2 pass)
            "AllowInvitesFrom": "adminsAndGuestInviters",
        },
    ],

    # =========================================================================
    # Directory Settings — for 5.3v1
    # =========================================================================
    "directory_settings": [
        {
            "DisplayName": "Consent Policy Settings",
            "Values": [
                # Admin consent workflow enabled (5.3 pass)
                {"Name": "EnableAdminConsentRequests", "Value": "true"},
            ],
        },
    ],

    # =========================================================================
    # Domain Settings — for 6.1v1
    # =========================================================================
    "domain_settings": [
        {
            "Id": "contoso.com",
            "IsRoot": True,
            "IsVerified": True,
            "AuthenticationType": "Managed",
            # INT_MAX means passwords never expire (6.1 pass)
            "PasswordValidityPeriodInDays": INT_MAX,
        },
    ],

    # =========================================================================
    # Privileged Users — for 7.1v1, 7.2v1, 7.3v1
    #
    # 3 Global Admins + 2 non-GA privileged users:
    #   7.1: 2 <= 3 <= 8 => PASS
    #   7.2: GlobalAdmins(3) > NotGlobalAdmins(2), ratio=1.5 > 1 => FAIL
    #   7.3: All OnPremisesImmutableId=null => PASS (all cloud-only)
    # =========================================================================
    "privileged_users": [
        {"DisplayName": "Alice Admin", "roles": ["Global Administrator"], "OnPremisesImmutableId": None},
        {"DisplayName": "Bob Admin", "roles": ["Global Administrator"], "OnPremisesImmutableId": None},
        {"DisplayName": "Carol Admin", "roles": ["Global Administrator"], "OnPremisesImmutableId": None},
        {"DisplayName": "Dave Operator", "roles": ["User Administrator"], "OnPremisesImmutableId": None},
        {"DisplayName": "Eve Operator", "roles": ["Exchange Administrator"], "OnPremisesImmutableId": None},
    ],

    # =========================================================================
    # Privileged Roles — empty array; only needed for 7.4-7.9 and 3.6
    # which are not in our target set. The PrivRolesSet computation handles
    # empty arrays gracefully (returns empty set).
    # =========================================================================
    "privileged_roles": [],

    # =========================================================================
    # ScubaGear Config — empty; exclusion checks pass via the
    # "both-exclusion-lists-empty" path in UserExclusionsFullyExempt, etc.
    # =========================================================================
    "scuba_config": {},

    # Module version for report URL generation (cosmetic only)
    "module_version": "1.8.0",
}


if __name__ == "__main__":
    output_path = "/app/tenant_input.json"
    with open(output_path, "w") as f:
        json.dump(tenant_config, f, indent=2)
    print(f"Wrote {output_path}")
