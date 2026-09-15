#!/usr/bin/env python3

"""
Fix Spring Boot 2.x → 3.0 property key renames and removals in
application.properties.
"""


def fix_application_properties():
    """Apply Spring Boot 3.0 property key renames and removals."""
    filepath = "/app/src/main/resources/application.properties"
    with open(filepath, 'r') as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        stripped = line.strip()

        # Rename: server.max-http-header-size → server.max-http-request-header-size
        if stripped.startswith("server.max-http-header-size") and "request" not in stripped:
            line = line.replace(
                "server.max-http-header-size",
                "server.max-http-request-header-size"
            )
            print("  Renamed: server.max-http-header-size → server.max-http-request-header-size")

        # Remove: management.endpoint.configprops.additional-keys-to-sanitize
        if "additional-keys-to-sanitize" in stripped:
            print(f"  Removed deprecated: {stripped}")
            continue

        new_lines.append(line)

    with open(filepath, 'w') as f:
        f.writelines(new_lines)

    print("Fixed application.properties")


def main():
    fix_application_properties()


if __name__ == '__main__':
    main()
