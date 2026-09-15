#!/usr/bin/env python3

"""
Analyze the broken Flux cluster configuration and produce a corrected version.

Diagnosis approach:
1. Parse the broken TOML config to understand current resource/queue/policy setup
2. Identify each misconfiguration through structural analysis
3. Generate a corrected config that satisfies all requirements
"""

import os
import sys
import re


def load_broken_config(path="/app/broken-config/config.toml"):
    """Load broken config as text for analysis."""
    with open(path) as f:
        return f.read()


def parse_resource_config_blocks(config_text):
    """Extract [[resource.config]] blocks and their properties."""
    blocks = []
    current_block = None
    for line in config_text.split("\n"):
        line_stripped = line.strip()
        if line_stripped == "[[resource.config]]":
            if current_block is not None:
                blocks.append(current_block)
            current_block = {}
        elif current_block is not None:
            if line_stripped.startswith("[") or line_stripped == "":
                if line_stripped.startswith("[") and not line_stripped.startswith("[[resource"):
                    blocks.append(current_block)
                    current_block = None
                continue
            match = re.match(r'(\w+)\s*=\s*(.*)', line_stripped)
            if match:
                key, value = match.group(1), match.group(2).strip()
                current_block[key] = value
    if current_block is not None:
        blocks.append(current_block)
    return blocks


def diagnose_issues(config_text):
    """Identify configuration bugs through structural analysis."""
    issues = []

    # Parse resource config blocks
    blocks = parse_resource_config_blocks(config_text)

    # Bug 1: Check for blanket property assignment covering all nodes
    for block in blocks:
        hosts = block.get("hosts", "")
        props = block.get("properties", "")
        if "0-7" in hosts and "debug" in props and "batch" in props:
            issues.append(
                "PROPERTY_LEAKAGE: All 8 nodes assigned both 'debug' and "
                "'batch' properties in a single resource.config entry. "
                "This destroys queue resource isolation — both queues can "
                "schedule on every node."
            )
            break

    # Bug 2: Check for missing GPU property
    gpu_property_found = False
    for block in blocks:
        props = block.get("properties", "")
        if "gpu" in props:
            gpu_property_found = True
            break
    if not gpu_property_found:
        issues.append(
            "MISSING_GPU_PROPERTY: No resource.config entry assigns the "
            "'gpu' property. GPU hardware (gpus='0-1') is configured on "
            "node[6-7] but the gpu queue's requires=['gpu'] constraint "
            "matches no resources — GPU jobs can never be scheduled."
        )

    # Bug 3: Check for node exclusion
    exclude_match = re.search(r'exclude\s*=\s*"([^"]*)"', config_text)
    if exclude_match:
        excluded = exclude_match.group(1)
        issues.append(
            f"NODE_EXCLUDED: resource.exclude='{excluded}' withholds a node "
            f"from scheduling, reducing available GPU capacity."
        )

    # Bug 4: Check default queue
    queue_match = re.search(
        r'\[policy\.jobspec\.defaults\.system\]\s*\n\s*queue\s*=\s*"(\w+)"',
        config_text
    )
    if queue_match:
        default_queue = queue_match.group(1)
        if default_queue != "batch":
            issues.append(
                f"WRONG_DEFAULT_QUEUE: Default queue is '{default_queue}' "
                f"instead of 'batch'. Jobs submitted without -q are routed "
                f"to the '{default_queue}' queue."
            )

    return issues


def generate_fixed_config():
    """
    Generate a corrected TOML configuration that satisfies:
    - 8 nodes (node[0-7]), 4 cores each
    - debug queue: nodes 0-1 only (property 'debug')
    - batch queue: nodes 2-5 only (property 'batch')
    - gpu queue: nodes 6-7 only (property 'gpu', 2 GPUs each)
    - default queue: batch
    - no node exclusions
    - all queues independent
    """
    sections = []

    # Access: allow root to run flux in container
    sections.append("[access]")
    sections.append("allow-root-owner = true")
    sections.append("")

    # Resource: NO exclude directive
    # Base resource: all 8 nodes, 4 cores each
    sections.append("[[resource.config]]")
    sections.append('hosts = "node[0-7]"')
    sections.append('cores = "0-3"')
    sections.append("")

    # Debug property: ONLY nodes 0-1
    sections.append("[[resource.config]]")
    sections.append('hosts = "node[0-1]"')
    sections.append('properties = ["debug"]')
    sections.append("")

    # Batch property: ONLY nodes 2-5
    sections.append("[[resource.config]]")
    sections.append('hosts = "node[2-5]"')
    sections.append('properties = ["batch"]')
    sections.append("")

    # GPU property + hardware: ONLY nodes 6-7
    sections.append("[[resource.config]]")
    sections.append('hosts = "node[6-7]"')
    sections.append('gpus = "0-1"')
    sections.append('properties = ["gpu"]')
    sections.append("")

    # Queue definitions with isolation via requires
    sections.append("[queues.debug]")
    sections.append('requires = ["debug"]')
    sections.append('policy.limits.duration = "30m"')
    sections.append("")

    sections.append("[queues.batch]")
    sections.append('requires = ["batch"]')
    sections.append('policy.limits.duration = "8h"')
    sections.append("")

    sections.append("[queues.gpu]")
    sections.append('requires = ["gpu"]')
    sections.append('policy.limits.duration = "4h"')
    sections.append("")

    # Default queue: batch
    sections.append("[policy.jobspec.defaults.system]")
    sections.append('queue = "batch"')
    sections.append("")

    return "\n".join(sections)


def main():
    # Load and analyze broken config
    config_text = load_broken_config()

    print("=" * 60)
    print("FLUX CONFIGURATION DIAGNOSIS")
    print("=" * 60)

    issues = diagnose_issues(config_text)
    if issues:
        print(f"\nFound {len(issues)} configuration issue(s):\n")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}\n")
    else:
        print("\nNo issues detected (unexpected).\n")

    # Generate corrected configuration
    fixed_config = generate_fixed_config()

    # Write to output directory
    output_dir = "/app/fixed-config"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "config.toml")

    with open(output_path, "w") as f:
        f.write(fixed_config)

    print("=" * 60)
    print("FIXES APPLIED")
    print("=" * 60)
    print("""
  1. Split blanket properties=['debug','batch'] into per-group entries:
     - node[0-1]: properties=['debug']
     - node[2-5]: properties=['batch']
     - node[6-7]: properties=['gpu'] + gpus='0-1'

  2. Added 'gpu' property to node[6-7] resource config
     (hardware gpus alone do not create a scheduling property)

  3. Removed resource.exclude='node6' so all 8 nodes are schedulable

  4. Changed default queue from 'gpu' to 'batch'
""")
    print(f"Fixed configuration written to {output_path}")


if __name__ == "__main__":
    main()
