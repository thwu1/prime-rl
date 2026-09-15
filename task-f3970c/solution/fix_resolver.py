#!/usr/bin/env python3
"""
Fixes the 5 bugs in /app/resolve.py by applying targeted patches
derived from comparing the code against the specification.

Bug 1: Template merge order — config applied before templates (should be after)
Bug 2: Missing {{config}} substitution in label values
Bug 3: Hook commands replaced instead of concatenated
Bug 4: Three-part port format drops the bind IP address
Bug 5: Hostname underscores not normalized to hyphens
"""


def read_file(path):
    with open(path, "r") as f:
        return f.read()


def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)


def fix_merge_order(code):
    """Bug 1: Templates must be applied first, container config last."""
    # Remove the premature config application before the template loop
    code = code.replace(
        "    # Apply container configuration\n"
        "    apply_layer(merged, config, config_name)\n"
        "\n"
        "    # Apply referenced templates\n",
        "    # Apply referenced templates first\n",
    )
    # Insert config application after the template loop, before extraction
    code = code.replace(
        "    # Extract top-level fields from the container config"
        " (not from templates)",
        "    # Apply container configuration last (highest priority)\n"
        "    apply_layer(merged, config, config_name)\n"
        "\n"
        "    # Extract top-level fields from the container config"
        " (not from templates)",
    )
    return code


def fix_label_substitution(code):
    """Bug 2: Labels must get {{config}} substitution like env does."""
    code = code.replace(
        "merged['labels'][key] = str(value)",
        "merged['labels'][key] = str(value)"
        ".replace('{{config}}', config_name)",
    )
    return code


def fix_hook_merging(code):
    """Bug 3: Same-name hooks must concatenate command lists."""
    code = code.replace(
        "            merged['hooks'][hook_name] = commands",
        "            if hook_name in merged['hooks']:\n"
        "                merged['hooks'][hook_name] = "
        "merged['hooks'][hook_name] + list(commands)\n"
        "            else:\n"
        "                merged['hooks'][hook_name] = list(commands)",
    )
    return code


def fix_port_format(code):
    """Bug 4: Three-part port bindings must preserve the bind IP."""
    code = code.replace(
        '                result.append(f"-p {parts[1]}:{parts[2]}")',
        '                result.append(f"-p {entry}")',
    )
    return code


def fix_hostname_normalization(code):
    """Bug 5: Underscores in hostnames must be replaced with hyphens."""
    code = code.replace(
        '        hostname = f"{machine_hostname}-{config_name}"\n'
        "\n"
        "    return hostname",
        '        hostname = f"{machine_hostname}-{config_name}"\n'
        "\n"
        "    hostname = hostname.replace('_', '-')\n"
        "    return hostname",
    )
    return code


def main():
    resolver_path = "/app/resolve.py"
    code = read_file(resolver_path)

    original = code
    code = fix_merge_order(code)
    assert code != original, "Fix 1 (merge order) did not apply"

    prev = code
    code = fix_label_substitution(code)
    assert code != prev, "Fix 2 (label substitution) did not apply"

    prev = code
    code = fix_hook_merging(code)
    assert code != prev, "Fix 3 (hook merging) did not apply"

    prev = code
    code = fix_port_format(code)
    assert code != prev, "Fix 4 (port format) did not apply"

    prev = code
    code = fix_hostname_normalization(code)
    assert code != prev, "Fix 5 (hostname normalization) did not apply"

    write_file(resolver_path, code)
    print("All 5 bugs fixed in resolve.py")


if __name__ == "__main__":
    main()
