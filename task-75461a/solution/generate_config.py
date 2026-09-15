#!/usr/bin/env python3
"""
Generate Flux TOML configuration from the cluster specification YAML.

Reads /app/cluster_spec.yaml and writes /app/flux_config/system.toml
with the correct resource definitions, queue constraints, policy
defaults, and job-manager settings.
"""

import os
import yaml
import toml

SPEC_PATH = "/app/cluster_spec.yaml"
CONFIG_DIR = "/app/flux_config"
CONFIG_PATH = os.path.join(CONFIG_DIR, "system.toml")


def main():
    # ---- Read cluster specification ----
    with open(SPEC_PATH) as f:
        spec = yaml.safe_load(f)

    config = {}

    # ---- Resource section ----
    resource = {}

    # Verification bypass (required for test instances without real hardware)
    if spec.get("resource", {}).get("noverify"):
        resource["noverify"] = True

    # Static node exclusion (config-time, different from runtime drain)
    exclude_val = spec.get("resource", {}).get("exclude")
    if exclude_val is not None:
        resource["exclude"] = str(exclude_val)

    # Resource config array: maps hostlists to core sets and properties
    config_entries = []
    for node_spec in spec["resource"]["nodes"]:
        entry = {"hosts": node_spec["hosts"]}
        if "cores" in node_spec:
            entry["cores"] = node_spec["cores"]
        if "gpus" in node_spec:
            entry["gpus"] = node_spec["gpus"]
        if "properties" in node_spec:
            entry["properties"] = node_spec["properties"]
        config_entries.append(entry)

    resource["config"] = config_entries
    config["resource"] = resource

    # ---- Queue configuration ----
    queues = {}
    default_queue = None

    for qname, qconf in spec["queues"].items():
        queue_entry = {}
        if "requires" in qconf:
            queue_entry["requires"] = qconf["requires"]
        if "policy" in qconf:
            queue_entry["policy"] = qconf["policy"]
        queues[qname] = queue_entry
        if qconf.get("is_default"):
            default_queue = qname

    config["queues"] = queues

    # ---- Default queue policy ----
    if default_queue:
        config["policy"] = {
            "jobspec": {
                "defaults": {
                    "system": {
                        "queue": default_queue
                    }
                }
            }
        }

    # ---- Job manager settings ----
    jm_spec = spec.get("job_manager", {})
    if jm_spec:
        jm = {}
        if "inactive_num_limit" in jm_spec:
            jm["inactive-num-limit"] = jm_spec["inactive_num_limit"]
        if "inactive_age_limit" in jm_spec:
            jm["inactive-age-limit"] = jm_spec["inactive_age_limit"]
        config["job-manager"] = jm

    # ---- Write TOML ----
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        toml.dump(config, f)

    print(f"Configuration written to {CONFIG_PATH}")

    # Print for debugging
    with open(CONFIG_PATH) as f:
        print(f.read())


if __name__ == "__main__":
    main()
