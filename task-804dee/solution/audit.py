#!/usr/bin/env python3
"""
Discourse Docker Configuration Auditor


Scans Discourse Docker container YAML definitions against bundled-plugin
lists, system constraints, and documented conventions.  Produces a structured
JSON audit report at /app/report.json.
"""

import json
import os
import re

import yaml


# ── Loaders ──────────────────────────────────────────────────────


def load_bundled_plugins(path):
    with open(path) as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]


def load_constraints(path):
    with open(path) as fh:
        return json.load(fh)


def load_configs(config_dir):
    configs = {}
    for fname in sorted(os.listdir(config_dir)):
        if fname.endswith(".yml"):
            with open(os.path.join(config_dir, fname)) as fh:
                configs[fname] = yaml.safe_load(fh)
    return configs


# ── Helpers ──────────────────────────────────────────────────────


def parse_memory_mb(value):
    """Convert a memory string like '4096MB' or '2GB' to integer megabytes."""
    val = str(value).strip().upper()
    if val.endswith("GB"):
        return int(val[:-2]) * 1024
    if val.endswith("MB"):
        return int(val[:-2])
    if val.endswith("KB"):
        return int(val[:-2]) // 1024
    return int(val)


def extract_host_ports(expose_list):
    """Return list of (host_port, container_port) from expose entries."""
    ports = []
    for entry in expose_list or []:
        parts = str(entry).split(":")
        if len(parts) == 2:
            ports.append(int(parts[0]))
        elif len(parts) == 3:
            ports.append(int(parts[1]))
    return ports


def extract_cloned_plugins(hooks):
    """Extract plugin names from git-clone commands inside hooks."""
    plugins = []
    if not hooks:
        return plugins
    for action in hooks.get("after_code", []):
        if not isinstance(action, dict) or "exec" not in action:
            continue
        for cmd in action["exec"].get("cmd", []):
            m = re.search(
                r"git\s+clone\s+https://github\.com/discourse/([^\s]+?)(?:\.git)?\s*$",
                cmd,
            )
            if m:
                plugins.append(m.group(1).rstrip("."))
    return plugins


# ── Audit engine ─────────────────────────────────────────────────


def audit(config_dir, reference_dir):
    bundled = load_bundled_plugins(
        os.path.join(reference_dir, "bundled_plugins.txt")
    )
    constraints = load_constraints(os.path.join(reference_dir, "constraints.json"))
    configs = load_configs(config_dir)

    issues = []
    port_map = {}  # host_port -> [filenames]

    for fname, cfg in configs.items():
        if not cfg:
            continue

        templates = cfg.get("templates", [])
        env = cfg.get("env", {}) or {}
        params = cfg.get("params", {}) or {}

        # ── Bundled plugins ──────────────────────────────────────
        for plugin in extract_cloned_plugins(cfg.get("hooks")):
            clean = plugin.replace(".git", "")
            if clean in bundled:
                issues.append(
                    {
                        "file": fname,
                        "category": "bundled_plugin",
                        "severity": "warning",
                        "description": (
                            f"Plugin '{clean}' is now bundled with Discourse and "
                            f"should not be git-cloned in hooks. Remove the clone line."
                        ),
                    }
                )

        # ── Memory overcommit ────────────────────────────────────
        if "db_shared_buffers" in params:
            buf_mb = parse_memory_mb(params["db_shared_buffers"])
            max_mb = (
                constraints["system_memory_mb"]
                * constraints["db_shared_buffers_max_pct"]
                / 100
            )
            if buf_mb > max_mb:
                issues.append(
                    {
                        "file": fname,
                        "category": "memory_overcommit",
                        "severity": "error",
                        "description": (
                            f"db_shared_buffers is {params['db_shared_buffers']} "
                            f"({buf_mb}MB), exceeding {constraints['db_shared_buffers_max_pct']}% "
                            f"of system memory ({constraints['system_memory_mb']}MB). "
                            f"Maximum recommended: {int(max_mb)}MB."
                        ),
                    }
                )

        # ── Host-port tracking (cross-file conflict detection) ───
        for port in extract_host_ports(cfg.get("expose")):
            port_map.setdefault(port, []).append(fname)

        # ── Invalid hostname ─────────────────────────────────────
        hostname = env.get("DISCOURSE_HOSTNAME", "")
        if hostname and (
            "example.com" in hostname or "example.org" in hostname
        ):
            issues.append(
                {
                    "file": fname,
                    "category": "invalid_hostname",
                    "severity": "error",
                    "description": (
                        f"DISCOURSE_HOSTNAME is '{hostname}', which is a placeholder "
                        f"example value. Set it to your actual domain."
                    ),
                }
            )

        # ── Missing developer emails ────────────────────────────
        if "DISCOURSE_DEVELOPER_EMAILS" in env:
            emails = str(env["DISCOURSE_DEVELOPER_EMAILS"]).strip()
            if not emails:
                issues.append(
                    {
                        "file": fname,
                        "category": "missing_developer_emails",
                        "severity": "error",
                        "description": (
                            "DISCOURSE_DEVELOPER_EMAILS is empty. At least one admin "
                            "email address is required for initial setup."
                        ),
                    }
                )

        # ── SMTP port / TLS mismatch ────────────────────────────
        smtp_port = env.get("DISCOURSE_SMTP_PORT")
        smtp_force_tls = env.get("DISCOURSE_SMTP_FORCE_TLS")
        if smtp_port is not None and smtp_force_tls is not None:
            port_val = int(str(smtp_port))
            tls_on = str(smtp_force_tls).lower() in ("true", "1", "yes")
            if port_val == 587 and tls_on:
                issues.append(
                    {
                        "file": fname,
                        "category": "smtp_misconfiguration",
                        "severity": "warning",
                        "description": (
                            "DISCOURSE_SMTP_PORT is 587 (STARTTLS) but "
                            "DISCOURSE_SMTP_FORCE_TLS is true (implicit TLS). "
                            "Use port 465 for implicit TLS, or disable FORCE_TLS "
                            "for port 587."
                        ),
                    }
                )

        # ── SSL template without Let's Encrypt ──────────────────
        has_ssl = any("web.ssl.template" in t for t in templates)
        has_le = any("web.letsencrypt.ssl.template" in t for t in templates)
        if has_ssl and not has_le:
            issues.append(
                {
                    "file": fname,
                    "category": "ssl_misconfiguration",
                    "severity": "warning",
                    "description": (
                        "web.ssl.template.yml is included but "
                        "web.letsencrypt.ssl.template.yml is missing. "
                        "SSL will not work without a certificate source."
                    ),
                }
            )

        # ── PostgreSQL container missing --shm-size ─────────────
        has_pg = any("postgres" in t for t in templates)
        docker_args = cfg.get("docker_args", "") or ""
        if has_pg and "--shm-size" not in str(docker_args):
            issues.append(
                {
                    "file": fname,
                    "category": "missing_shm_size",
                    "severity": "warning",
                    "description": (
                        f"Container uses a PostgreSQL template but docker_args "
                        f"does not set --shm-size. Docker defaults to "
                        f"{constraints['default_docker_shm_mb']}MB shared memory, "
                        f"which can cause 'could not resize shared memory segment' "
                        f"errors. Recommended minimum: "
                        f"{constraints['min_recommended_shm_mb']}MB."
                    ),
                }
            )

    # ── Cross-file port conflicts ────────────────────────────────
    for port, files in sorted(port_map.items()):
        if len(files) > 1:
            issues.append(
                {
                    "file": files[1],
                    "category": "port_conflict",
                    "severity": "error",
                    "description": (
                        f"Host port {port} is exposed in multiple containers: "
                        f"{', '.join(files)}. Only one container can bind a host "
                        f"port at a time."
                    ),
                }
            )

    # ── Summary ──────────────────────────────────────────────────
    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")

    return {
        "issues": issues,
        "summary": {
            "total": len(issues),
            "errors": errors,
            "warnings": warnings,
            "files_scanned": len(configs),
        },
    }


# ── Main ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    config_dir = "/app/configs"
    reference_dir = "/app/reference"

    report = audit(config_dir, reference_dir)

    with open("/app/report.json", "w") as fh:
        json.dump(report, fh, indent=2)

    print(json.dumps(report, indent=2))
