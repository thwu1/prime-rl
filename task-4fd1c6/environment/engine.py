#!/usr/bin/env python3
"""
Secure Command Template Engine v2.3.1
Network proxy configuration command builder with metacharacter sanitization.

Substitutes user-controlled values into shell command templates with
sanitization to prevent command injection.
"""
import subprocess
import json
import re
import sys
import os

# --- Sanitizers for each execution context ---

BLOCKLIST_EXEC = set("'`\";&<>|(){}")

ALLOWLIST_PATTERN = re.compile(r'[a-zA-Z0-9._@:/-]+')

SANITIZE_BINARY = "/app/bin/sanitize_direct"


def sanitize_exec_context(value):
    """Sanitizer for exec-mode proxy commands.
    Blocks known shell metacharacters used for command injection."""
    if not value:
        raise ValueError("Empty value")
    if value[0] == '-':
        raise ValueError("Value cannot start with dash")
    for ch in value:
        if ch in BLOCKLIST_EXEC:
            raise ValueError(f"Blocked character: {repr(ch)}")
    return value


def sanitize_direct_context(value):
    """Sanitizer for direct-mode tunnel commands.
    Delegates to compiled binary filter for performance."""
    if not value:
        raise ValueError("Empty value")
    result = subprocess.run(
        [SANITIZE_BINARY, value],
        capture_output=True,
        text=True,
        timeout=5
    )
    if result.returncode != 0:
        raise ValueError(
            f"Binary filter rejected: {result.stderr.strip()}"
        )
    return result.stdout


def sanitize_checked_context(value):
    """Sanitizer using allowlist regex.
    Only permits alphanumeric characters and common safe symbols."""
    if not value:
        raise ValueError("Empty value")
    if not ALLOWLIST_PATTERN.match(value):
        raise ValueError("Value contains disallowed characters")
    return value


# --- Execution contexts ---

CONTEXTS = {
    "exec_proxy": {
        "template": "proxy-connect --user %u --host %h --port %p",
        "execution": "exec",
        "sanitizer": sanitize_exec_context,
    },
    "direct_tunnel": {
        "template": "tunnel-connect %u@%h %p",
        "execution": "direct",
        "sanitizer": sanitize_direct_context,
    },
    "checked_health": {
        "template": "health-check --target %u@%h:%p",
        "execution": "direct",
        "sanitizer": sanitize_checked_context,
    },
}


def build_command(context_name, username, hostname, port):
    """Build a shell command from template and user-supplied values."""
    ctx = CONTEXTS[context_name]
    sanitizer = ctx["sanitizer"]

    safe_user = sanitizer(username)
    safe_host = sanitizer(hostname)
    safe_port = sanitizer(str(port))

    cmd = ctx["template"]
    cmd = cmd.replace("%u", safe_user)
    cmd = cmd.replace("%h", safe_host)
    cmd = cmd.replace("%p", safe_port)

    return cmd


def execute_command(context_name, username, hostname, port):
    """Build and execute a command in the given context."""
    ctx = CONTEXTS[context_name]
    cmd = build_command(context_name, username, hostname, port)

    if ctx["execution"] == "exec":
        full_cmd = f"exec {cmd}"
    else:
        full_cmd = cmd

    result = subprocess.run(
        ["bash", "-c", full_cmd],
        capture_output=True,
        text=True,
        timeout=5
    )
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: engine.py <context> [payload.json]")
        print("Contexts: exec_proxy, direct_tunnel, checked_health")
        sys.exit(1)

    context = sys.argv[1]

    if len(sys.argv) > 2:
        with open(sys.argv[2]) as f:
            payload = json.load(f)
    else:
        payload = {
            "username": input("Username: "),
            "hostname": input("Hostname: "),
            "port": input("Port: ")
        }

    try:
        result = execute_command(
            context,
            payload["username"],
            payload["hostname"],
            payload["port"]
        )
        print(f"Exit code: {result.returncode}")
        if result.stdout:
            print(f"Stdout: {result.stdout}")
        if result.stderr:
            print(f"Stderr: {result.stderr}")
    except ValueError as e:
        print(f"Sanitizer blocked: {e}")
    except subprocess.TimeoutExpired:
        print("Command timed out")
