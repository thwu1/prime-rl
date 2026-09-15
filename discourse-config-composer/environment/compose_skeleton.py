#!/usr/bin/env python3
"""
Discourse Docker YAML Template Composition Engine

The Discourse Docker launcher (https://github.com/discourse/discourse_docker)
uses Ruby running inside Docker containers to parse and compose YAML configuration
files for Discourse deployments. This tool re-implements that composition logic
in Python as a standalone utility.

Study /app/reference/launcher to understand the merging rules. Pay close attention
to WHICH sections are merged across all templates vs. which are read only from
the main config file — this distinction is critical.

Usage:
    python3 compose.py <config_file> <config_name> [--base-dir DIR]

Arguments:
    config_file: Path to the container YAML configuration file
    config_name: Name of the container (used for {{config}} substitution)
    --base-dir:  Base directory for resolving template paths
                 (default: parent of config file's directory if in containers/)

Output:
    JSON document to stdout with these fields:
    - config_name: the config name
    - env: list of "-e KEY=VALUE" strings
    - env_map: dict of merged environment variables
    - ports: list of "-p X:Y" or "--expose N" strings
    - raw_ports: list of raw port specifications before formatting
    - volumes: list of "-v HOST:GUEST" strings
    - labels: list of "-l KEY=VALUE" strings
    - label_map: dict of merged labels
    - docker_args: the docker_args string
    - boot_command: boot command (default "/sbin/boot")
    - run_image: run image (default "local_discourse/{config_name}")
    - params: dict of merged params
    - hooks: dict of merged hooks (hook_name -> list of command entries)
    - issues: list of {code, severity, message} dicts for detected problems
    - template_errors: list of {template, error} dicts for unresolvable templates
    - templates_used: list of template paths from the config
"""

import sys
import json

# Known bundled plugins that should NOT be manually cloned in hooks.
# Manually cloning these causes conflicts with the versions bundled in Discourse.
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

# Issue codes for configuration analysis.
# Each detected issue should be reported with one of these codes,
# a severity level, and a descriptive message.
ISSUE_CODES = [
    "SMTP_NOT_CONFIGURED",
    "HOSTNAME_NOT_CONFIGURED",
    "BUNDLED_PLUGIN",
    "MISSING_SHM_SIZE",
    "SHARED_BUFFERS_TOO_HIGH",
    "EXPOSED_DB_PORT",
    "EXPOSED_REDIS_PORT",
    "SSL_WITH_IP_HOSTNAME",
    "MISSING_LETSENCRYPT_EMAIL",
]


def main():
    if len(sys.argv) < 3:
        print("Usage: compose.py <config_file> <config_name> [--base-dir DIR]",
              file=sys.stderr)
        sys.exit(1)

    config_file = sys.argv[1]
    config_name = sys.argv[2]
    base_dir = None

    if len(sys.argv) > 4 and sys.argv[3] == '--base-dir':
        base_dir = sys.argv[4]

    # TODO: Implement the full template composition engine
    # Study /app/reference/launcher carefully to understand the rules.

    result = {}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
