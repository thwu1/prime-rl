#!/usr/bin/env python3
"""
Discourse Docker Deployment Analyzer

Reads a deployment manifest, resolves container configurations using the
resolver, performs cross-container validation, and generates docker-compose
YAML with proper service definitions and dependency inference.
"""

import argparse
import json
import subprocess
import sys

import yaml


def resolve_config(config_name, base_dir, hostname):
    """Run the resolver subprocess and return parsed JSON."""
    result = subprocess.run(
        [
            "python3", f"{base_dir}/resolve.py", config_name,
            "--base-dir", base_dir,
            "--hostname", hostname,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(
            f"Error resolving {config_name}: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)
    return json.loads(result.stdout)


def parse_published_ports(port_args):
    """Extract (bind_addr, host_port, container_port) from -p flags."""
    ports = []
    for arg in port_args:
        if not arg.startswith("-p "):
            continue
        spec = arg[3:]
        parts = spec.split(":")
        if len(parts) == 2:
            ports.append(("0.0.0.0", parts[0], parts[1]))
        elif len(parts) == 3:
            ports.append((parts[0], parts[1], parts[2]))
    return ports


def detect_port_conflicts(resolved):
    """Find containers that publish the same host port on the same interface."""
    findings = []
    bindings = {}
    for name, config in resolved.items():
        for bind_addr, host_port, _ in parse_published_ports(
            config.get("port_args", [])
        ):
            key = (bind_addr, host_port)
            bindings.setdefault(key, []).append(name)

    for (addr, port), containers in bindings.items():
        unique = sorted(set(containers))
        if len(unique) > 1:
            findings.append({
                "type": "port_conflict",
                "severity": "error",
                "containers": unique,
                "detail": (
                    f"Multiple containers bind port {addr}:{port}: "
                    f"{', '.join(unique)}"
                ),
            })
    return findings


def detect_bundled_plugins(resolved):
    """Warn about bundled plugin references detected by the resolver."""
    findings = []
    for name, config in resolved.items():
        plugins = config.get("bundled_plugins", [])
        if plugins:
            findings.append({
                "type": "bundled_plugin",
                "severity": "warning",
                "containers": [name],
                "detail": (
                    f"Container '{name}' references bundled plugins that "
                    f"should be removed: {', '.join(plugins)}"
                ),
            })
    return findings


def detect_localhost_binding(resolved):
    """Detect services bound to 127.0.0.1 that other containers depend on."""
    findings = []

    localhost_containers = set()
    for name, config in resolved.items():
        for bind_addr, _, _ in parse_published_ports(
            config.get("port_args", [])
        ):
            if bind_addr == "127.0.0.1":
                localhost_containers.add(name)

    for name, config in resolved.items():
        env = config.get("env", {})
        for var in ("DISCOURSE_DB_HOST", "DISCOURSE_REDIS_HOST"):
            ref = env.get(var, "")
            if ref in localhost_containers and ref != name:
                findings.append({
                    "type": "localhost_binding",
                    "severity": "error",
                    "containers": sorted([name, ref]),
                    "detail": (
                        f"Container '{name}' sets {var}='{ref}', but "
                        f"'{ref}' binds ports to 127.0.0.1 only, making "
                        f"them inaccessible from other containers"
                    ),
                })
    return findings


def generate_compose(resolved):
    """Generate docker-compose YAML from resolved configurations."""
    services = {}
    container_names = set(resolved.keys())

    for name, config in resolved.items():
        service = {
            "image": config.get("run_image", f"local_discourse/{name}"),
            "container_name": name,
            "hostname": config.get("hostname", ""),
            "mac_address": config.get("mac_address", ""),
            "command": config.get("boot_command", "/sbin/boot"),
            "environment": dict(config.get("env", {})),
        }

        vols = []
        for v in config.get("volumes", []):
            if isinstance(v, dict) and "volume" in v:
                vol = v["volume"]
                host = vol.get("host", "")
                guest = vol.get("guest", "")
                if host and guest:
                    vols.append(f"{host}:{guest}")
        service["volumes"] = vols

        ports = []
        expose = []
        for arg in config.get("port_args", []):
            if arg.startswith("-p "):
                ports.append(arg[3:])
            elif arg.startswith("--expose "):
                expose.append(arg[9:])
        if ports:
            service["ports"] = ports
        if expose:
            service["expose"] = expose

        depends = set()
        env = config.get("env", {})
        for var in ("DISCOURSE_DB_HOST", "DISCOURSE_REDIS_HOST"):
            ref = env.get(var, "")
            if ref in container_names and ref != name:
                depends.add(ref)
        if depends:
            service["depends_on"] = sorted(depends)

        services[name] = service

    compose = {"version": "3.8", "services": services}
    return yaml.dump(compose, default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a Discourse Docker deployment"
    )
    parser.add_argument("--base-dir", default="/app")
    args = parser.parse_args()

    manifest_path = f"{args.base_dir}/deployment.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    hostname = manifest.get("hostname", "testhost")
    containers = manifest["containers"]

    resolved = {}
    for name in containers:
        resolved[name] = resolve_config(name, args.base_dir, hostname)

    findings = []
    findings.extend(detect_port_conflicts(resolved))
    findings.extend(detect_bundled_plugins(resolved))
    findings.extend(detect_localhost_binding(resolved))

    compose_yaml = generate_compose(resolved)

    output = {"audit": findings, "compose": compose_yaml}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
