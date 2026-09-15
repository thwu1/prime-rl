#!/usr/bin/env python3
"""
Discourse Docker YAML Template Composition Engine — Reference Solution

Re-implements the template composition logic from the Discourse Docker
launcher script as a standalone Python tool.
"""

import sys
import os
import re
import json
import yaml

BUNDLED_PLUGINS = [
    "discourse-reactions", "discourse-apple-auth", "discourse-login-with-amazon",
    "discourse-lti", "discourse-microsoft-auth", "discourse-oauth2-basic",
    "discourse-openid-connect", "discourse-zendesk-plugin", "discourse-patreon",
    "discourse-graphviz", "discourse-rss-polling", "discourse-math",
    "discourse-chat-integration", "discourse-data-explorer", "discourse-post-voting",
    "discourse-user-notes", "discourse-staff-notes", "discourse-assign",
    "discourse-subscriptions", "discourse-hcaptcha", "discourse-gamification",
    "discourse-calendar", "discourse-question-answer", "discourse-adplugin",
    "discourse-affiliate", "discourse-github", "discourse-templates",
    "discourse-topic-voting", "discourse-policy", "discourse-solved",
    "discourse-ai", "discourse-cakeday",
]


def load_yaml(filepath):
    """Load a YAML file, returning {} on failure."""
    with open(filepath, "r") as fh:
        return yaml.safe_load(fh) or {}


def subst(value, config_name):
    """Replace {{config}} with config_name in a string."""
    if isinstance(value, str):
        return value.replace("{{config}}", config_name)
    return value


# ---------------------------------------------------------------------------
# Merging helpers — each mirrors the Ruby code embedded in the launcher
# ---------------------------------------------------------------------------

def merge_env(sources, config_name):
    """Merge env dicts across all sources (templates then main config).

    Launcher Ruby:
        env = {'LANG' => 'en_US.UTF-8'}
        input.split('_FILE_SEPERATOR_').each { |yml| env.merge!(... ['env']) }
    Later sources override earlier ones.  {{config}} is substituted in values.
    """
    env = {"LANG": "en_US.UTF-8"}
    for src in sources:
        for k, v in (src.get("env") or {}).items():
            env[k] = str(v)
    return {k: subst(v, config_name) for k, v in env.items()}


def merge_labels(sources, config_name):
    """Merge labels — same strategy as env."""
    labels = {}
    for src in sources:
        for k, v in (src.get("labels") or {}).items():
            labels[str(k)] = str(v)
    return {subst(k, config_name): subst(v, config_name) for k, v in labels.items()}


def merge_expose(sources):
    """Concatenate expose lists across ALL sources.

    Launcher Ruby:
        ports += (YAML.load(yml)['expose'] || [])
    """
    ports = []
    for src in sources:
        ports.extend(src.get("expose") or [])
    return ports


def format_ports(raw_ports):
    """Format raw port specs into Docker arguments.

    Launcher Ruby:
        ports.map { |p| p.to_s.include?(':') ? "-p\\n#{p}" : "--expose\\n#{p}" }
    """
    out = []
    for p in raw_ports:
        s = str(p)
        if ":" in s:
            out.append(f"-p {s}")
        else:
            out.append(f"--expose {s}")
    return out


def extract_volumes(config_data):
    """Extract volumes ONLY from the main config.

    Launcher:
        volumes=`cat $config_file | ... ruby -e "...YAML.load(STDIN...)['volumes']..."`
    Note: set_volumes reads only from $config_file, NOT from merged templates.
    """
    result = []
    for v in config_data.get("volumes") or []:
        vol = v.get("volume", {})
        host = vol.get("host", "")
        guest = vol.get("guest", "")
        if host and guest:
            result.append(f"-v {host}:{guest}")
    return result


def merge_params(sources):
    """Merge params dicts across all sources."""
    params = {}
    for src in sources:
        params.update(src.get("params") or {})
    return params


def merge_hooks(sources):
    """Merge hooks by name, appending command lists."""
    hooks = {}
    for src in sources:
        for name, cmds in (src.get("hooks") or {}).items():
            hooks.setdefault(name, [])
            if isinstance(cmds, list):
                hooks[name].extend(cmds)
            else:
                hooks[name].append(cmds)
    return hooks


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------

def _parse_mb(value):
    """Parse a memory string like '256MB' or '4GB' into megabytes."""
    m = re.match(r"^(\d+)\s*(MB|GB|mb|gb|M|G)?$", str(value))
    if not m:
        return None
    num = int(m.group(1))
    unit = (m.group(2) or "MB").upper()
    if unit in ("GB", "G"):
        return num * 1024
    return num


def detect_issues(config_data, env, params, template_names, hooks, raw_ports):
    """Detect common Discourse self-hosting misconfigurations."""
    issues = []

    uses_postgres = any("postgres" in t for t in template_names)
    uses_web = any("web.template" in t for t in template_names)
    uses_ssl = any("ssl" in t and "letsencrypt" not in t for t in template_names)
    uses_le = any("letsencrypt" in t for t in template_names)

    hostname = env.get("DISCOURSE_HOSTNAME", "")
    is_ip = bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", hostname))
    is_example = "example.com" in hostname

    # --- SMTP ---
    if uses_web:
        smtp = env.get("DISCOURSE_SMTP_ADDRESS", "")
        skip = env.get("DISCOURSE_SKIP_EMAIL_SETUP", "")
        if skip != "1" and (not smtp or "example.com" in smtp):
            issues.append({
                "code": "SMTP_NOT_CONFIGURED",
                "severity": "critical",
                "message": f"SMTP address is not configured (currently: '{smtp}'). Email delivery will fail.",
            })

    # --- Hostname ---
    if is_example:
        issues.append({
            "code": "HOSTNAME_NOT_CONFIGURED",
            "severity": "critical",
            "message": f"DISCOURSE_HOSTNAME is still set to an example value: '{hostname}'",
        })

    # --- SSL + bad hostname ---
    if uses_ssl and is_ip:
        issues.append({
            "code": "SSL_WITH_IP_HOSTNAME",
            "severity": "critical",
            "message": (
                f"SSL template is enabled but DISCOURSE_HOSTNAME is an IP address "
                f"({hostname}). SSL certificates cannot be issued for bare IPs."
            ),
        })
    if uses_ssl and is_example:
        issues.append({
            "code": "SSL_WITH_INVALID_HOSTNAME",
            "severity": "critical",
            "message": (
                f"SSL template is enabled but DISCOURSE_HOSTNAME is still an example "
                f"value ({hostname})."
            ),
        })

    # --- Let's Encrypt email ---
    if uses_le and not env.get("LETSENCRYPT_ACCOUNT_EMAIL", ""):
        issues.append({
            "code": "MISSING_LETSENCRYPT_EMAIL",
            "severity": "critical",
            "message": "Let's Encrypt SSL template is used but LETSENCRYPT_ACCOUNT_EMAIL is not set.",
        })

    # --- PostgreSQL shared memory ---
    docker_args = config_data.get("docker_args", "") or ""
    if uses_postgres and "--shm-size" not in docker_args:
        issues.append({
            "code": "MISSING_SHM_SIZE",
            "severity": "warning",
            "message": (
                "PostgreSQL template is used but --shm-size is not set in docker_args. "
                "Default Docker shm (64 MB) may cause 'could not resize shared memory "
                "segment' errors."
            ),
        })

    # --- db_shared_buffers ---
    sb = params.get("db_shared_buffers", "")
    if sb:
        mb = _parse_mb(sb)
        if mb is not None and mb > 2048:
            issues.append({
                "code": "SHARED_BUFFERS_TOO_HIGH",
                "severity": "warning",
                "message": (
                    f"db_shared_buffers is set to {sb}, which may be too high. "
                    "Keep it under 25 % of total system memory."
                ),
            })

    # --- Exposed DB / Redis ports ---
    for p in raw_ports:
        s = str(p)
        if ":" not in s:
            continue  # --expose only, not a host mapping
        parts = s.split(":")
        container_port = parts[-1].split("/")[0]
        bound_all = (len(parts) == 2) or (len(parts) == 3 and parts[0] != "127.0.0.1")
        if container_port == "5432" and bound_all:
            issues.append({
                "code": "EXPOSED_DB_PORT",
                "severity": "critical",
                "message": (
                    f"PostgreSQL port 5432 is exposed on all interfaces ({s}). "
                    "Bind to 127.0.0.1 or use a firewall."
                ),
            })
        if container_port == "6379" and bound_all:
            issues.append({
                "code": "EXPOSED_REDIS_PORT",
                "severity": "critical",
                "message": (
                    f"Redis port 6379 is exposed on all interfaces ({s}). "
                    "Bind to 127.0.0.1 or use a firewall."
                ),
            })

    # --- Bundled plugins in hooks ---
    for hook_name, entries in hooks.items():
        for entry in entries:
            if not isinstance(entry, dict) or "exec" not in entry:
                continue
            exec_val = entry["exec"]
            cmds = []
            if isinstance(exec_val, dict):
                c = exec_val.get("cmd", [])
                cmds = c if isinstance(c, list) else [c]
            elif isinstance(exec_val, str):
                cmds = [exec_val]
            for cmd in cmds:
                if not isinstance(cmd, str) or "git clone" not in cmd:
                    continue
                m = re.search(r"git clone\s+\S+/([A-Za-z0-9_-]+?)(?:\.git)?\s*$", cmd)
                if m and m.group(1) in BUNDLED_PLUGINS:
                    issues.append({
                        "code": "BUNDLED_PLUGIN",
                        "severity": "warning",
                        "message": (
                            f"Plugin '{m.group(1)}' is now bundled with Discourse "
                            "and should not be manually cloned in hooks."
                        ),
                    })

    return issues


# ---------------------------------------------------------------------------
# Main composition
# ---------------------------------------------------------------------------

def compose(config_file, config_name, base_dir=None):
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(config_file))
        if os.path.basename(base_dir) == "containers":
            base_dir = os.path.dirname(base_dir)

    config_data = load_yaml(config_file)
    template_names = config_data.get("templates") or []

    # Load templates in order
    templates = []
    template_errors = []
    for tpl in template_names:
        full = os.path.join(base_dir, tpl)
        if os.path.exists(full):
            try:
                templates.append(load_yaml(full))
            except Exception as exc:
                template_errors.append({"template": tpl, "error": str(exc)})
        else:
            template_errors.append({"template": tpl, "error": f"File not found: {full}"})

    # All sources: templates in declared order, then main config (highest priority)
    all_sources = templates + [config_data]

    # Merge each section per its own rule
    env_map = merge_env(all_sources, config_name)
    label_map = merge_labels(all_sources, config_name)
    raw_ports = merge_expose(all_sources)
    volumes = extract_volumes(config_data)          # main config only
    params = merge_params(all_sources)
    hooks = merge_hooks(all_sources)

    docker_args = config_data.get("docker_args", "") or ""   # main config only

    boot_command = config_data.get("boot_command", "") or ""  # main config only
    if not boot_command:
        if not config_data.get("no_boot_command"):
            boot_command = "/sbin/boot"

    run_image = config_data.get("run_image", "") or ""        # main config only
    if not run_image:
        run_image = f"local_discourse/{config_name}"

    issues = detect_issues(config_data, env_map, params, template_names, hooks, raw_ports)

    return {
        "config_name": config_name,
        "env": [f"-e {k}={v}" for k, v in env_map.items()],
        "env_map": env_map,
        "ports": format_ports(raw_ports),
        "raw_ports": [str(p) for p in raw_ports],
        "volumes": volumes,
        "labels": [f"-l {k}={v}" for k, v in label_map.items()],
        "label_map": label_map,
        "docker_args": docker_args,
        "boot_command": boot_command,
        "run_image": run_image,
        "params": params,
        "hooks": hooks,
        "issues": issues,
        "template_errors": template_errors,
        "templates_used": template_names,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: compose.py <config_file> <config_name> [--base-dir DIR]",
              file=sys.stderr)
        sys.exit(1)

    config_file = sys.argv[1]
    config_name = sys.argv[2]
    base_dir = None
    if len(sys.argv) > 4 and sys.argv[3] == "--base-dir":
        base_dir = sys.argv[4]

    result = compose(config_file, config_name, base_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
