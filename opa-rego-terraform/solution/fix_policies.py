#!/usr/bin/env python3

"""
Design and implement all five OPA Rego policies for the infrastructure
compliance validation system, and fix manifest configuration errors.

The policies directory starts empty. Each policy must be created from
scratch by analyzing the Terraform plan JSON structures and the
requirements in the manifest. Two manifest query paths are misconfigured
and must also be corrected.

Policies created:
1. s3_security.rego  - S3 versioning, KMS encryption, public access block
2. iam_trust.rego    - IAM role trust relationship for Lambda
3. network_ha.rego   - Multi-AZ VPC with HTTPS-only ingress
4. iam_least_privilege.rego - IAM wildcard action/resource detection
5. s3_lifecycle.rego - S3 lifecycle rule with expiration

Manifest fixes:
- iam_trust query path: data.iam_trust_validation.is_valid -> data.iam_trust.is_valid
- s3_lifecycle query path: data.s3_lifecycle_rules.is_valid -> data.s3_lifecycle.is_valid
"""

import json
import os

POLICIES_DIR = "/app/policies"
MANIFEST_PATH = "/app/manifest.json"


def write_policy(filename, content):
    path = os.path.join(POLICIES_DIR, filename)
    with open(path, "w") as f:
        f.write(content)
    print(f"Created {path}")


# ── Policy 1: s3_security.rego ──────────────────────────────────────────────
# Terraform plan JSON nests versioning, encryption config, and rules inside
# arrays at every level. The public access block is a separate resource type
# (aws_s3_bucket_public_access_block, not aws_s3_bucket_public_access_block_config).
write_policy("s3_security.rego", """\
package s3_security

default is_valid = false

has_versioning {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_s3_bucket"
    resource.values.versioning[0].enabled == true
}

has_encryption {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_s3_bucket"
    resource.values.server_side_encryption_configuration[0].rule[0].apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms"
}

has_public_access_block {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_s3_bucket_public_access_block"
    resource.values.block_public_acls == true
    resource.values.block_public_policy == true
    resource.values.ignore_public_acls == true
    resource.values.restrict_public_buckets == true
}

is_valid {
    has_versioning
    has_encryption
    has_public_access_block
}
""")


# ── Policy 2: iam_trust.rego ────────────────────────────────────────────────
# Uses resource_changes section to inspect IAM role trust policies.
# Must target aws_iam_role (not aws_iam_policy) and use assume_role_policy
# (not trust_policy). json.unmarshal parses the embedded JSON string.
write_policy("iam_trust.rego", """\
package iam_trust

default is_valid = false

is_valid_role {
    resource := input.resource_changes[_]
    resource.type == "aws_iam_role"
    policy_str := resource.change.after.assume_role_policy
    policy := json.unmarshal(policy_str)
    statement := policy.Statement[_]
    statement.Principal.Service == "lambda.amazonaws.com"
    statement.Action == "sts:AssumeRole"
}

has_policy_attachment {
    resource := input.resource_changes[_]
    resource.type == "aws_iam_role_policy_attachment"
    resource.change.after.role
    resource.change.after.policy_arn
}

is_valid {
    is_valid_role
    has_policy_attachment
}
""")


# ── Policy 3: network_ha.rego ───────────────────────────────────────────────
# Validates VPC, multi-AZ subnets, and HTTPS-only ingress.
# AZ diversity must use planned_values (not configuration, which has
# 'expressions' instead of 'values'). Ingress uses from_port (not source_port).
write_policy("network_ha.rego", """\
package network_ha

default is_valid = false

has_vpc {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_vpc"
    resource.values.cidr_block
    resource.values.enable_dns_support == true
}

has_minimum_subnets {
    subnets := [r | r := input.planned_values.root_module.resources[_]; r.type == "aws_subnet"]
    count(subnets) >= 2
}

has_az_diversity {
    resource1 := input.planned_values.root_module.resources[_]
    resource1.type == "aws_subnet"
    az1 := resource1.values.availability_zone

    resource2 := input.planned_values.root_module.resources[_]
    resource2.type == "aws_subnet"
    az2 := resource2.values.availability_zone

    az1 != az2
}

has_restricted_ingress {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_security_group"
    ingress := resource.values.ingress[_]
    ingress.from_port == 443
    ingress.to_port == 443
    ingress.protocol == "tcp"
}

is_valid {
    has_vpc
    has_minimum_subnets
    has_az_diversity
    has_restricted_ingress
}
""")


# ── Policy 4: iam_least_privilege.rego ──────────────────────────────────────
# Detects IAM policies with wildcard Action + Resource combinations.
# The critical design decision: the Terraform field is 'policy' (not
# 'policy_document'). If the wrong field is referenced, json.unmarshal
# receives undefined, silently returning undefined, which makes
# wildcard_violation always undefined, making 'not wildcard_violation'
# vacuously true — a subtle semantic trap.
write_policy("iam_least_privilege.rego", """\
package iam_least_privilege

default is_valid = false

has_iam_policy {
    input.planned_values.root_module.resources[_].type == "aws_iam_policy"
}

wildcard_violation {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_iam_policy"
    policy := json.unmarshal(resource.values.policy)
    statement := policy.Statement[_]
    statement.Action == "*"
    statement.Resource == "*"
}

is_valid {
    has_iam_policy
    not wildcard_violation
}
""")


# ── Policy 5: s3_lifecycle.rego ─────────────────────────────────────────────
# Validates that every S3 bucket has at least one enabled lifecycle rule
# with a positive expiration period. The key design insight: expiration
# in Terraform plan JSON is an array of objects, requiring [0] indexing.
# Without the array index, the path is undefined, causing the helper
# function to never match.
write_policy("s3_lifecycle.rego", """\
package s3_lifecycle

default is_valid = false

has_s3_bucket {
    input.planned_values.root_module.resources[_].type == "aws_s3_bucket"
}

bucket_missing_lifecycle {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_s3_bucket"
    not has_valid_lifecycle(resource)
}

has_valid_lifecycle(res) {
    rule := res.values.lifecycle_rule[_]
    rule.enabled == true
    rule.expiration[0].days > 0
}

is_valid {
    has_s3_bucket
    not bucket_missing_lifecycle
}
""")


# ── Fix manifest configuration ─────────────────────────────────────────────
# Two query paths are misconfigured:
# 1. iam_trust uses data.iam_trust_validation.is_valid but package is iam_trust
# 2. s3_lifecycle uses data.s3_lifecycle_rules.is_valid but package is s3_lifecycle
with open(MANIFEST_PATH) as f:
    manifest = json.load(f)

manifest["policies"]["iam_trust"]["query"] = "data.iam_trust.is_valid"
manifest["policies"]["s3_lifecycle"]["query"] = "data.s3_lifecycle.is_valid"

with open(MANIFEST_PATH, "w") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")

print("Fixed manifest: corrected query paths for iam_trust and s3_lifecycle")
print("All policies created and manifest corrected.")
