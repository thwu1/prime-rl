#!/usr/bin/env python3
"""
Discourse Docker Configuration Resolver

Resolves a Discourse Docker container configuration by compositing
template YAML files according to the resolution specification.

Usage:
    python3 resolve.py <config_name> [--base-dir DIR] [--hostname HOST]
"""

import sys
import os
import argparse
import json
import hashlib
import re

import yaml


BUNDLED_PLUGINS = [
    "discourse-reactions",
    "discourse-apple-auth",
    "discourse-login-with-amazon",
    "discourse-lti",
    "discourse-microsoft-auth",
    "discourse-oauth2-basic",
    "discourse-openid-connect",
    "discourse-zendesk-plugin",
    "discourse-patreon",
    "discourse-graphviz",
    "discourse-rss-polling",
    "discourse-math",
    "discourse-chat-integration",
    "discourse-data-explorer",
    "discourse-post-voting",
    "discourse-user-notes",
    "discourse-staff-notes",
    "discourse-assign",
    "discourse-subscriptions",
    "discourse-hcaptcha",
    "discourse-gamification",
    "discourse-calendar",
    "discourse-question-answer",
    "discourse-adplugin",
    "discourse-affiliate",
    "discourse-github",
    "discourse-templates",
    "discourse-topic-voting",
    "discourse-policy",
    "discourse-solved",
    "discourse-ai",
    "discourse-cakeday",
]

BASE_IMAGE = "discourse/base:2.0.20260521-0047"

CONFIG_NAME_PATTERN = re.compile(r'^[a-z0-9._-]+$')


def validate_config_name(name):
    """Validate that the config name contains only allowed characters.

    Config names must not contain uppercase letters, spaces, or special
    characters. Only lowercase letters, digits, dots, underscores, and
    hyphens are allowed.
    """
    if not CONFIG_NAME_PATTERN.match(name):
        raise ValueError(
            f"Config name '{name}' contains invalid characters. "
            "Only lowercase letters, digits, dots, underscores, "
            "and hyphens are allowed."
        )
    return name


def load_yaml_file(filepath):
    """Load and parse a YAML file, returning an empty dict if the file
    contains no data."""
    with open(filepath, 'r') as f:
        data = yaml.safe_load(f)
    return data if data is not None else {}


def apply_layer(merged, layer, config_name):
    """Apply a single configuration layer to the accumulated merged config.

    Handles merging of env, labels, expose, volumes, links, hooks, and
    params according to their respective merge strategies.
    """
    # env: dict merge with {{config}} substitution
    if 'env' in layer and layer['env']:
        for key, value in layer['env'].items():
            merged['env'][key] = str(value).replace('{{config}}', config_name)

    # labels: dict merge
    if 'labels' in layer and layer['labels']:
        for key, value in layer['labels'].items():
            merged['labels'][key] = str(value)

    # expose: list accumulation
    if 'expose' in layer and layer['expose']:
        for entry in layer['expose']:
            merged['expose'].append(str(entry))

    # volumes: list accumulation
    if 'volumes' in layer and layer['volumes']:
        merged['volumes'].extend(layer['volumes'])

    # links: list accumulation
    if 'links' in layer and layer['links']:
        merged['links'].extend(layer['links'])

    # hooks: merge by hook name
    if 'hooks' in layer and layer['hooks']:
        for hook_name, commands in layer['hooks'].items():
            merged['hooks'][hook_name] = commands

    # params: dict merge
    if 'params' in layer and layer['params']:
        merged['params'].update(layer['params'])


def resolve_ports(expose_list):
    """Convert accumulated expose entries to Docker port arguments.

    Entries with ':' become -p flags; entries without become --expose flags.
    Duplicates are removed, preserving first-occurrence order.
    """
    result = []
    seen = set()

    for entry in expose_list:
        if entry in seen:
            continue
        seen.add(entry)

        if ':' in entry:
            parts = entry.split(':')
            if len(parts) == 2:
                result.append(f"-p {entry}")
            elif len(parts) == 3:
                # ip:host:container — bind to specific interface
                result.append(f"-p {parts[1]}:{parts[2]}")
            else:
                result.append(f"-p {entry}")
        else:
            result.append(f"--expose {entry}")

    return result


def format_volume_args(volumes):
    """Convert volume definitions to Docker -v arguments."""
    result = []
    for vol_entry in volumes:
        if isinstance(vol_entry, dict) and 'volume' in vol_entry:
            vol = vol_entry['volume']
            host_path = vol.get('host', '')
            guest_path = vol.get('guest', '')
            if host_path and guest_path:
                result.append(f"-v {host_path}:{guest_path}")
    return result


def compute_hostname(config_name, env, machine_hostname=None):
    """Compute the container hostname based on configuration.

    Uses DISCOURSE_HOSTNAME if DOCKER_USE_HOSTNAME is "true",
    otherwise uses <machine_hostname>-<config_name>.
    """
    docker_use_hostname = env.get('DOCKER_USE_HOSTNAME', '')
    discourse_hostname = env.get('DISCOURSE_HOSTNAME', 'localhost')

    if docker_use_hostname == "true":
        hostname = discourse_hostname
    else:
        if machine_hostname is None:
            import socket
            try:
                machine_hostname = socket.gethostname().split('.')[0]
            except Exception:
                machine_hostname = "localhost"
        hostname = f"{machine_hostname}-{config_name}"

    return hostname


def compute_mac_address(hostname):
    """Compute a deterministic MAC address from the hostname.

    Uses MD5 hash of the hostname with trailing newline (matching
    the shell behavior of: echo $hostname | md5sum).
    Format: 02:xx:xx:xx:xx:xx using first 5 pairs of the hex digest.
    """
    md5_hex = hashlib.md5((hostname + '\n').encode()).hexdigest()
    return (
        f"02:{md5_hex[0:2]}:{md5_hex[2:4]}:"
        f"{md5_hex[4:6]}:{md5_hex[6:8]}:{md5_hex[8:10]}"
    )


def detect_bundled_plugins(hooks):
    """Detect references to bundled plugins in hook exec commands.

    Scans all hook command lists for git clone URLs that reference
    plugins in the BUNDLED_PLUGINS list.
    """
    found = []
    for hook_name, commands in hooks.items():
        if not isinstance(commands, list):
            continue
        for cmd_entry in commands:
            if not isinstance(cmd_entry, dict) or 'exec' not in cmd_entry:
                continue
            exec_block = cmd_entry['exec']
            if not isinstance(exec_block, dict):
                continue
            cmds = exec_block.get('cmd', [])
            if isinstance(cmds, str):
                cmds = [cmds]
            if not isinstance(cmds, list):
                continue
            for cmd_str in cmds:
                if not isinstance(cmd_str, str):
                    continue
                for plugin in BUNDLED_PLUGINS:
                    if f"github.com/discourse/{plugin}" in cmd_str:
                        found.append(plugin)
    return sorted(set(found))


def resolve_config(config_name, base_dir, machine_hostname=None):
    """Resolve a container configuration by compositing templates.

    Loads the container definition, applies referenced templates,
    and returns the fully resolved configuration as a dict.
    """
    validate_config_name(config_name)

    config_path = os.path.join(base_dir, "containers", f"{config_name}.yml")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config = load_yaml_file(config_path)
    template_refs = config.get('templates', [])

    # Initialize the merged configuration accumulator
    merged = {
        'env': {},
        'labels': {},
        'expose': [],
        'volumes': [],
        'links': [],
        'hooks': {},
        'params': {},
    }

    # Apply container configuration
    apply_layer(merged, config, config_name)

    # Apply referenced templates
    for tmpl_ref in template_refs:
        tmpl_path = os.path.join(base_dir, tmpl_ref)
        if not os.path.exists(tmpl_path):
            raise FileNotFoundError(f"Template not found: {tmpl_path}")
        tmpl_data = load_yaml_file(tmpl_path)
        apply_layer(merged, tmpl_data, config_name)

    # Extract top-level fields from the container config (not from templates)
    merged['docker_args'] = config.get('docker_args', '')
    merged['boot_command'] = config.get('boot_command', '/sbin/boot')
    merged['run_image'] = config.get('run_image', f'local_discourse/{config_name}')
    merged['base_image'] = config.get('base_image', BASE_IMAGE)

    # Detect bundled plugins in hooks
    merged['bundled_plugins'] = detect_bundled_plugins(merged.get('hooks', {}))

    # Generate port arguments from expose list
    merged['port_args'] = resolve_ports(merged['expose'])

    # Generate volume arguments
    merged['volume_args'] = format_volume_args(merged['volumes'])

    # Compute hostname and MAC address
    merged['hostname'] = compute_hostname(
        config_name, merged['env'], machine_hostname
    )
    merged['mac_address'] = compute_mac_address(merged['hostname'])

    return merged


def main():
    parser = argparse.ArgumentParser(
        description='Resolve Discourse Docker container configuration'
    )
    parser.add_argument(
        'config_name',
        help='Name of the container configuration (without .yml extension)'
    )
    parser.add_argument(
        '--base-dir', default='/app',
        help='Base directory containing containers/ and templates/ '
             '(default: /app)'
    )
    parser.add_argument(
        '--hostname', default=None,
        help='Override machine hostname for hostname computation'
    )

    args = parser.parse_args()

    try:
        result = resolve_config(args.config_name, args.base_dir, args.hostname)
        print(json.dumps(result, indent=2, sort_keys=True))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
