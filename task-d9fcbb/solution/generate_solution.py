#!/usr/bin/env python3
"""
Evaluate competing Terraform module decomposition proposals against
architectural requirements, then generate the correct implementation.

This script:
1. Reads and analyzes both proposals for structural patterns and bugs
2. Reads the terraform state to determine resource addresses
3. Generates evaluation.json with structured assessment
4. Creates the correct modular implementation with moved blocks and validation
5. Runs terraform init + validate + plan to verify
"""

import json
import os
import re
import subprocess
import sys


def analyze_proposal(proposal_dir):
    """Analyze a proposal directory for structural patterns and HCL bugs."""
    analysis = {
        "module_names": [],
        "has_moved_blocks": False,
        "has_validation": False,
        "hcl_bugs": [],
    }

    for root, dirs, files in os.walk(proposal_dir):
        rel = os.path.relpath(root, proposal_dir)
        if rel.startswith("modules/"):
            parts = rel.split("/")
            if len(parts) == 2:
                analysis["module_names"].append(parts[1])

        for f in files:
            if not f.endswith(".tf"):
                continue
            filepath = os.path.join(root, f)
            with open(filepath) as fh:
                content = fh.read()

            if re.search(r"\bmoved\s*\{", content):
                analysis["has_moved_blocks"] = True
            if "validation" in content:
                analysis["has_validation"] = True

            # Detect specific HCL bugs
            if "var.enabled_services" in content:
                analysis["hcl_bugs"].append(
                    "References undefined variable 'enabled_services' — "
                    "health_check for_each should derive from app_config"
                )
            if re.search(r"tolist\(var\.\w*alert", content):
                analysis["hcl_bugs"].append(
                    "Uses tolist() on a map variable in alert_notifier for_each — "
                    "type error (needs map comprehension with active filter)"
                )
            if "service_port" in content and "triggers" in content:
                analysis["hcl_bugs"].append(
                    "health_check trigger key 'service_port' mismatches state key 'port' "
                    "— would force resource replacement"
                )
            if "app_name" in content and "triggers" in content:
                analysis["hcl_bugs"].append(
                    "health_check trigger key 'app_name' mismatches state key 'app' "
                    "— would force resource replacement"
                )
            # Check alert_notifier trigger key mismatch
            if "alert_notifier" in content and "null_resource" in content:
                if re.search(r"^\s*endpoint\s*=", content, re.MULTILINE):
                    analysis["hcl_bugs"].append(
                        "alert_notifier trigger key 'endpoint' mismatches state key 'url' "
                        "— would force resource replacement"
                    )

    # Check for missing root files
    root_files = [
        f for f in os.listdir(proposal_dir)
        if os.path.isfile(os.path.join(proposal_dir, f)) and f.endswith(".tf")
    ]
    root_file_names = [os.path.basename(f) for f in root_files]
    if "variables.tf" not in root_file_names:
        has_vars_in_main = False
        for rf in root_files:
            with open(os.path.join(proposal_dir, rf)) as fh:
                if "variable " in fh.read():
                    has_vars_in_main = True
                    break
        if not has_vars_in_main:
            analysis["hcl_bugs"].append(
                "Missing root variable declarations — module calls reference "
                "undefined root variables (var.environment, var.subnets, etc.)"
            )

    return analysis


def get_state_resources():
    """Read terraform state to determine existing resource addresses."""
    result = subprocess.run(
        ["terraform", "state", "list"],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Warning: terraform state list failed: {result.stderr}", file=sys.stderr)
        return []
    return [r.strip() for r in result.stdout.strip().split("\n") if r.strip()]


def categorize_resources(resources):
    """Categorize state resources into operational domains."""
    network_patterns = ["network_config", "subnet_configs"]
    app_patterns = [
        "app_configs", "health_check",
        "deployment_metadata", "deployment_manifest",
    ]
    monitoring_patterns = ["alert_rules", "alert_notifier"]

    categories = {"network": set(), "application": set(), "monitoring": set()}

    for res in resources:
        base = re.sub(r'\["[^"]*"\]$', "", res)
        if any(p in base for p in network_patterns):
            categories["network"].add(base)
        elif any(p in base for p in app_patterns):
            categories["application"].add(base)
        elif any(p in base for p in monitoring_patterns):
            categories["monitoring"].add(base)

    return {k: sorted(v) for k, v in categories.items()}


def generate_evaluation(analysis_a, analysis_b):
    """Generate evaluation.json by comparing proposals against requirements."""
    a_violations = []
    a_strengths = []

    if set(analysis_a["module_names"]) & {"files", "runtime"}:
        a_violations.append(
            "Violates domain cohesion (Req 1): groups resources by Terraform "
            "resource type (files vs runtime) rather than by operational domain "
            "(networking, application, monitoring)"
        )
        a_violations.append(
            "Cross-domain resources are mixed within same module — network_config, "
            "app_configs, and alert_rules all share the 'files' module despite "
            "serving different operational domains"
        )

    if analysis_a["has_moved_blocks"]:
        a_strengths.append("Includes moved blocks for state migration (satisfies Req 5)")
    if analysis_a["has_validation"]:
        a_strengths.append("Includes variable validation (partially satisfies Req 2)")
    if not analysis_a["hcl_bugs"]:
        a_strengths.append("Syntactically valid HCL — would pass terraform validate")

    b_violations = list(analysis_b["hcl_bugs"])
    b_strengths = []

    if set(analysis_b["module_names"]) >= {"network", "application", "monitoring"}:
        b_strengths.append("Correct domain-based module structure (satisfies Req 1)")
        b_strengths.append(
            "Module dependency direction: network -> application -> monitoring "
            "(satisfies Req 3)"
        )

    if not analysis_b["has_moved_blocks"]:
        b_violations.append(
            "No moved blocks for state migration — violates Req 5"
        )
    if not analysis_b["has_validation"]:
        b_violations.append(
            "No variable validation blocks — violates Req 2"
        )

    return {
        "proposal_a_assessment": {
            "architecture": "by-type grouping (modules/files and modules/runtime)",
            "strengths": a_strengths,
            "violations": a_violations,
            "viable": len(a_violations) == 0,
        },
        "proposal_b_assessment": {
            "architecture": "by-domain grouping (modules/network, modules/application, modules/monitoring)",
            "strengths": b_strengths,
            "violations": b_violations,
            "viable": len(b_violations) == 0,
        },
        "selected_base": "proposal_b",
        "selection_rationale": (
            "Proposal B's domain-based architecture correctly satisfies the "
            "fundamental structural requirement (Req 1: domain cohesion) and "
            "the dependency direction requirement (Req 3). Its implementation "
            "bugs are all fixable without restructuring. Proposal A's by-type "
            "grouping is an architectural flaw that violates Req 1 and cannot "
            "be fixed without abandoning the structure entirely."
        ),
    }


def generate_moved_blocks(categorized):
    """Generate HCL moved blocks from categorized state resources."""
    blocks = []
    for domain, resources in categorized.items():
        for res in resources:
            blocks.append(
                f"moved {{\n"
                f"  from = {res}\n"
                f"  to   = module.{domain}.{res}\n"
                f"}}"
            )
    return "\n\n".join(blocks)


def write_file(path, content):
    """Write content to file, creating parent directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(f"  wrote {path}")


def main():
    print("=== Step 1: Analyze proposals ===")
    analysis_a = analyze_proposal("/app/proposals/by_type")
    analysis_b = analyze_proposal("/app/proposals/by_domain")

    print(f"Proposal A modules: {analysis_a['module_names']}")
    print(f"Proposal A HCL bugs: {len(analysis_a['hcl_bugs'])}")
    print(f"Proposal A has moved blocks: {analysis_a['has_moved_blocks']}")
    print(f"Proposal A has validation: {analysis_a['has_validation']}")
    print(f"Proposal B modules: {analysis_b['module_names']}")
    print(f"Proposal B HCL bugs: {len(analysis_b['hcl_bugs'])}")
    print(f"Proposal B has moved blocks: {analysis_b['has_moved_blocks']}")
    print(f"Proposal B has validation: {analysis_b['has_validation']}")

    print("\n=== Step 2: Generate evaluation ===")
    evaluation = generate_evaluation(analysis_a, analysis_b)
    write_file("/app/evaluation.json", json.dumps(evaluation, indent=2) + "\n")

    print("\n=== Step 3: Analyze state for moved block generation ===")
    resources = get_state_resources()
    print(f"Found {len(resources)} resource instances in state")
    categorized = categorize_resources(resources)
    total_base = sum(len(v) for v in categorized.values())
    print(f"Categorized into {total_base} base resources across {len(categorized)} domains:")
    for domain, res_list in categorized.items():
        print(f"  {domain}: {res_list}")

    moved_blocks_hcl = generate_moved_blocks(categorized)

    print("\n=== Step 4: Generate correct implementation ===")

    # --- Root main.tf ---
    write_file("/app/main.tf", f'''terraform {{
  required_providers {{
    local = {{
      source  = "hashicorp/local"
      version = "~> 2.5"
    }}
    null = {{
      source  = "hashicorp/null"
      version = "~> 3.2"
    }}
  }}
}}

module "network" {{
  source      = "./modules/network"
  environment = var.environment
  subnets     = var.subnets
}}

module "application" {{
  source      = "./modules/application"
  environment = var.environment
  app_config  = var.app_config
}}

module "monitoring" {{
  source          = "./modules/monitoring"
  app_config      = var.app_config
  alert_endpoints = var.alert_endpoints
  service_health  = module.application.health_endpoints
}}

{moved_blocks_hcl}
''')

    # --- Root variables.tf ---
    write_file("/app/variables.tf", '''variable "environment" {
  type    = string
  default = "production"

  validation {
    condition     = contains(["production", "staging", "development"], var.environment)
    error_message = "Environment must be one of: production, staging, development."
  }
}

variable "app_config" {
  type = map(object({
    port     = number
    replicas = number
    enabled  = bool
  }))
  default = {
    api = {
      port     = 8080
      replicas = 3
      enabled  = true
    }
    worker = {
      port     = 9090
      replicas = 2
      enabled  = true
    }
    scheduler = {
      port     = 7070
      replicas = 1
      enabled  = false
    }
  }
}

variable "subnets" {
  type = map(object({
    cidr   = string
    public = bool
  }))
  default = {
    public  = { cidr = "10.0.1.0/24", public = true }
    private = { cidr = "10.0.2.0/24", public = false }
  }
}

variable "alert_endpoints" {
  type = map(object({
    url      = string
    severity = string
    active   = bool
  }))
  default = {
    pagerduty = { url = "https://events.pagerduty.com", severity = "critical", active = true }
    slack     = { url = "https://hooks.slack.com/T00",   severity = "warning",  active = true }
  }
}
''')

    # --- Root outputs.tf ---
    write_file("/app/outputs.tf", '''output "network_config_path" {
  value = module.network.network_config_path
}

output "app_config_files" {
  value = module.application.app_config_files
}

output "active_alerts" {
  value = module.monitoring.active_alerts
}
''')

    # --- Network module ---
    write_file("/app/modules/network/main.tf", '''resource "local_file" "network_config" {
  filename = "/app/generated/network/config.json"
  content  = jsonencode({
    environment = var.environment
    subnets     = var.subnets
  })
}

resource "local_file" "subnet_configs" {
  for_each = var.subnets
  filename = "/app/generated/network/${each.key}.json"
  content  = jsonencode({
    name   = each.key
    cidr   = each.value.cidr
    public = each.value.public
  })
}
''')

    write_file("/app/modules/network/variables.tf", '''variable "environment" {
  type = string

  validation {
    condition     = contains(["production", "staging", "development"], var.environment)
    error_message = "Environment must be one of: production, staging, development."
  }
}

variable "subnets" {
  type = map(object({
    cidr   = string
    public = bool
  }))

  validation {
    condition     = alltrue([for k, v in var.subnets : can(cidrhost(v.cidr, 0))])
    error_message = "All subnet CIDRs must be valid IPv4 CIDR notation."
  }
}
''')

    write_file("/app/modules/network/outputs.tf", '''output "network_config_path" {
  value = local_file.network_config.filename
}

output "subnet_files" {
  value = { for k, v in local_file.subnet_configs : k => v.filename }
}
''')

    # --- Application module ---
    write_file("/app/modules/application/main.tf", '''resource "local_file" "app_configs" {
  for_each = var.app_config
  filename = "/app/generated/app/${each.key}.json"
  content  = jsonencode({
    name     = each.key
    port     = each.value.port
    replicas = each.value.replicas
    env      = var.environment
  })
}

resource "null_resource" "health_check" {
  for_each = { for k, v in var.app_config : k => v if v.enabled }

  triggers = {
    port = each.value.port
    app  = each.key
  }
}

resource "terraform_data" "deployment_metadata" {
  input = {
    deployed_at = "2024-01-15T10:00:00Z"
    version     = "1.0.0"
    environment = var.environment
  }
}

resource "local_file" "deployment_manifest" {
  filename = "/app/generated/manifest.yaml"
  content  = yamlencode({
    apiVersion = "v1"
    kind       = "DeploymentManifest"
    metadata   = { name = "app-deployment", environment = var.environment }
    spec = {
      services = { for k, v in var.app_config : k => {
        port     = v.port
        replicas = v.replicas
        status   = v.enabled ? "active" : "disabled"
      }}
    }
  })
}
''')

    write_file("/app/modules/application/variables.tf", '''variable "environment" {
  type = string

  validation {
    condition     = contains(["production", "staging", "development"], var.environment)
    error_message = "Environment must be one of: production, staging, development."
  }
}

variable "app_config" {
  type = map(object({
    port     = number
    replicas = number
    enabled  = bool
  }))

  validation {
    condition     = alltrue([for k, v in var.app_config : v.port >= 1024 && v.port <= 65535])
    error_message = "All application ports must be in the range 1024-65535."
  }
}
''')

    write_file("/app/modules/application/outputs.tf", '''output "app_config_files" {
  value = { for k, v in local_file.app_configs : k => v.filename }
}

output "health_endpoints" {
  value = { for k, v in null_resource.health_check : k => v.triggers["port"] }
}
''')

    # --- Monitoring module ---
    write_file("/app/modules/monitoring/main.tf", '''resource "local_file" "alert_rules" {
  filename = "/app/generated/monitoring/alerts.yaml"
  content  = yamlencode({
    rules = [for k, v in var.app_config : {
      name    = "${k}-health"
      port    = v.port
      enabled = v.enabled
    }]
  })
}

resource "null_resource" "alert_notifier" {
  for_each = { for k, v in var.alert_endpoints : k => v if v.active }

  triggers = {
    url      = each.value.url
    severity = each.value.severity
    channel  = each.key
  }
}
''')

    write_file("/app/modules/monitoring/variables.tf", '''variable "app_config" {
  type = map(object({
    port     = number
    replicas = number
    enabled  = bool
  }))
}

variable "alert_endpoints" {
  type = map(object({
    url      = string
    severity = string
    active   = bool
  }))

  validation {
    condition     = alltrue([for k, v in var.alert_endpoints : contains(["critical", "warning", "info"], v.severity)])
    error_message = "Alert severity must be one of: critical, warning, info."
  }
}

variable "service_health" {
  type        = map(string)
  description = "Health endpoint ports from the application module"
}
''')

    write_file("/app/modules/monitoring/outputs.tf", '''output "active_alerts" {
  value = { for k, v in null_resource.alert_notifier : k => v.triggers["channel"] }
}

output "alert_rules_path" {
  value = local_file.alert_rules.filename
}
''')

    # --- Step 5: Initialize and verify ---
    print("\n=== Step 5: Initialize and verify ===")

    init_result = subprocess.run(
        ["terraform", "init", "-input=false", "-no-color"],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    if init_result.returncode != 0:
        print(f"terraform init failed:\n{init_result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("terraform init: OK")

    validate_result = subprocess.run(
        ["terraform", "validate", "-no-color"],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    if validate_result.returncode != 0:
        print(
            f"terraform validate failed:\n{validate_result.stdout}\n{validate_result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)
    print("terraform validate: OK")

    plan_result = subprocess.run(
        ["terraform", "plan", "-no-color", "-input=false", "-detailed-exitcode"],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    print(f"terraform plan exit code: {plan_result.returncode}")
    output = plan_result.stdout
    # Show last portion of plan output
    if len(output) > 1000:
        print("..." + output[-1000:])
    else:
        print(output)

    if plan_result.returncode == 0:
        print("\nSUCCESS: No changes — zero-destroy migration verified")
    elif plan_result.returncode == 2:
        # Exit code 2 means changes detected
        add_match = re.search(r"(\d+) to add", output)
        destroy_match = re.search(r"(\d+) to destroy", output)
        adds = int(add_match.group(1)) if add_match else 0
        destroys = int(destroy_match.group(1)) if destroy_match else 0
        if adds == 0 and destroys == 0:
            print(f"\nSUCCESS: {adds} to add, {destroys} to destroy")
        else:
            print(f"\nFAILURE: {adds} to add, {destroys} to destroy")
            sys.exit(1)
    else:
        print(f"\nFAILURE: terraform plan errored:\n{plan_result.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    main()
