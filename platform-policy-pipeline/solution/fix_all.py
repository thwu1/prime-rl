#!/usr/bin/env python3
"""
Fix all platform policy and observability pipeline bugs by analyzing
the test expectations and correcting the policy/config logic.

"""

import yaml


def fix_k8s_helpers():
    """Fix Kubernetes resource quantity parsing bugs in lib/k8s.rego.

    Bug 1: parse_cpu for whole-number cores (e.g. "2") must multiply by 1000
            to convert to millicores. Currently returns raw number.
    Bug 2: parse_memory for Gi suffix uses 1000^3 (decimal gigabyte) instead
            of 1024^3 (binary gibibyte).
    """
    path = "/app/policies/lib/k8s.rego"
    with open(path) as f:
        content = f.read()

    # Bug 1: whole-core CPU values need * 1000 conversion
    content = content.replace(
        "millicores = to_number(quantity)\n",
        "millicores = to_number(quantity) * 1000\n",
    )

    # Bug 2: GiB uses binary prefix (1024^3), not decimal (1000^3)
    content = content.replace(
        "1000 * 1000 * 1000",
        "1024 * 1024 * 1024",
    )

    with open(path, "w") as f:
        f.write(content)
    print("[fixed] k8s.rego: CPU millicore conversion, GiB binary prefix")


def fix_pod_policy():
    """Fix pod governance policy bugs in pod_policy.rego.

    Bug 3: Digest-pinning check is inverted — flags images WITH digests
            instead of those WITHOUT. Must use 'not contains(...)'.
    Bug 4: all_containers set only includes spec.containers, missing
            spec.initContainers. Init containers must also be validated.
    Bug 5: CPU request-to-limit ratio computes limit/request instead of
            request/limit (ratio should be < 1.0 when request < limit).
    Bug 6: Memory request-to-limit ratio has the same inversion.
    """
    path = "/app/policies/pod_policy.rego"
    with open(path) as f:
        content = f.read()

    # Bug 3: digest check must use 'not contains' to flag missing digests
    content = content.replace(
        "    contains(image, \"@sha256:\")\n",
        "    not contains(image, \"@sha256:\")\n",
    )

    # Bug 4: add initContainers to the all_containers set
    content = content.replace(
        "all_containers contains container if {\n"
        "    some container in input.spec.containers\n"
        "}",
        "all_containers contains container if {\n"
        "    some container in input.spec.containers\n"
        "}\n"
        "\n"
        "all_containers contains container if {\n"
        "    some container in input.spec.initContainers\n"
        "}",
    )

    # Bug 5: CPU ratio should be request/limit, not limit/request
    content = content.replace(
        "ratio := cpu_limit / cpu_request",
        "ratio := cpu_request / cpu_limit",
    )

    # Bug 6: memory ratio should be request/limit, not limit/request
    content = content.replace(
        "ratio := mem_limit / mem_request",
        "ratio := mem_request / mem_limit",
    )

    with open(path, "w") as f:
        f.write(content)
    print("[fixed] pod_policy.rego: digest check, initContainers, ratio computations")


def fix_network_policy():
    """Fix network segmentation policy bugs in network_policy.rego.

    Bug 7: is_default_deny only verifies Ingress in policyTypes but does not
            check for Egress. A proper default-deny must cover both directions
            and must also verify that no egress rules are defined.
    """
    path = "/app/policies/network_policy.rego"
    with open(path) as f:
        content = f.read()

    old_rule = (
        '    "Ingress" in policy.spec.policyTypes\n'
        "    not policy.spec.ingress\n"
        "}"
    )
    new_rule = (
        '    "Ingress" in policy.spec.policyTypes\n'
        '    "Egress" in policy.spec.policyTypes\n'
        "    not policy.spec.ingress\n"
        "    not policy.spec.egress\n"
        "}"
    )
    content = content.replace(old_rule, new_rule)

    with open(path, "w") as f:
        f.write(content)
    print("[fixed] network_policy.rego: default-deny Egress check")


def fix_otel_config():
    """Fix OpenTelemetry Collector pipeline configuration bugs.

    Bug 8: metrics pipeline exports to otlp/jaeger (traces backend) instead
            of prometheusremotewrite (correct metrics backend).
    Bug 9: logs pipeline references undefined processor 'transform/logs'
            which is not declared in the processors section.
    Bug 10: traces pipeline has memory_limiter as second processor instead
             of first; it must be first to prevent OOM.
    """
    path = "/app/observability/collector-config.yaml"
    with open(path) as f:
        config = yaml.safe_load(f)

    pipelines = config["service"]["pipelines"]

    # Bug 8: metrics should export to prometheusremotewrite
    pipelines["metrics"]["exporters"] = ["prometheusremotewrite"]

    # Bug 9: remove undefined transform/logs from logs processors
    logs_procs = pipelines["logs"]["processors"]
    pipelines["logs"]["processors"] = [p for p in logs_procs if p != "transform/logs"]

    # Bug 10: ensure memory_limiter is first processor in traces pipeline
    traces_procs = pipelines["traces"]["processors"]
    if "memory_limiter" in traces_procs and traces_procs[0] != "memory_limiter":
        traces_procs.remove("memory_limiter")
        traces_procs.insert(0, "memory_limiter")
    pipelines["traces"]["processors"] = traces_procs

    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print("[fixed] collector-config.yaml: metrics exporter, undefined processor, processor ordering")


if __name__ == "__main__":
    fix_k8s_helpers()
    fix_pod_policy()
    fix_network_policy()
    fix_otel_config()
    print("\nAll 10 bugs fixed successfully.")
