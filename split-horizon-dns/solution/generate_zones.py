#!/usr/bin/env python3
"""
Generate correct BIND9 split-horizon DNS configuration and zone files from CSV data.
Replaces the broken deployment at /etc/bind/ with a working configuration.
Reads /app/hosts.csv and /app/services.csv; writes named.conf and zone files.
"""


import csv
import ipaddress
import os
import subprocess

ZONE = "infra.example.com"
SOA_SERIAL = "2024010101"

HOSTS_CSV = "/app/hosts.csv"
SERVICES_CSV = "/app/services.csv"

ZONES_DIR_INT = "/etc/bind/zones/internal"
ZONES_DIR_EXT = "/etc/bind/zones/external"
NAMED_CONF = "/etc/bind/named.conf"

IPV4_REVERSE_ZONE = "1.0.10.in-addr.arpa"
IPV6_REVERSE_ZONE = "0.0.0.0.0.0.0.0.0.0.0.0.0.0.d.f.ip6.arpa"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def read_hosts(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def read_services(path):
    with open(path) as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Zone file generation
# ---------------------------------------------------------------------------

def soa_header():
    """Return the SOA and NS block shared by all zone files."""
    return f"""$TTL 86400
@   IN  SOA ns1.{ZONE}. admin.{ZONE}. (
        {SOA_SERIAL}  ; Serial
        3600        ; Refresh
        900         ; Retry
        604800      ; Expire
        86400       ; Minimum TTL
)

        IN  NS  ns1.{ZONE}.
        IN  NS  ns2.{ZONE}.
"""


def generate_forward_zone(hosts, services, view="internal"):
    """Build a complete forward zone file for the given view."""
    lines = [soa_header()]

    # A records
    lines.append("; A records")
    for h in hosts:
        if view == "external" and h["ipv4_external"]:
            ip = h["ipv4_external"]
        else:
            ip = h["ipv4_internal"]
        lines.append(f"{h['hostname']:<12}IN  A       {ip}")
    lines.append("")

    # AAAA records
    lines.append("; AAAA records")
    for h in hosts:
        if h["ipv6"]:
            lines.append(f"{h['hostname']:<12}IN  AAAA    {h['ipv6']}")
    lines.append("")

    # Service records from CSV
    lines.append("; Service records")
    for svc in services:
        rt = svc["record_type"]
        name = svc["name"]
        value = svc["value"]
        if rt == "MX":
            lines.append(f"{name:<12}IN  MX      {svc['priority']} {value}")
        elif rt == "CNAME":
            lines.append(f"{name:<12}IN  CNAME   {value}")
        elif rt == "SRV":
            lines.append(
                f"{name} IN  SRV     "
                f"{svc['priority']} {svc['weight']} {svc['port']} {value}"
            )
        elif rt == "TXT":
            # Ensure value is quoted for the zone file
            txt = value if value.startswith('"') else f'"{value}"'
            lines.append(f"{name:<12}IN  TXT     {txt}")
    lines.append("")

    return "\n".join(lines) + "\n"


def generate_reverse_ipv4(hosts):
    """Build the IPv4 reverse zone file for 10.0.1.0/24."""
    lines = [soa_header()]
    lines.append("; PTR records")
    for h in hosts:
        last_octet = h["ipv4_internal"].split(".")[-1]
        lines.append(f"{last_octet:<12}IN  PTR     {h['hostname']}.{ZONE}.")
    lines.append("")
    return "\n".join(lines) + "\n"


def ipv6_reverse_host_part(ipv6_str, prefix_len=64):
    """
    Convert an IPv6 address to the host-part nibble string relative to
    the /prefix_len reverse zone.

    Example: fd00::10 with /64 -> '0.1.0.0.0.0.0.0.0.0.0.0.0.0.0.0'
    """
    addr = ipaddress.IPv6Address(ipv6_str)
    full_hex = addr.exploded.replace(":", "")  # 32 hex chars
    reversed_nibbles = list(reversed(full_hex))
    host_nibble_count = (128 - prefix_len) // 4
    return ".".join(reversed_nibbles[:host_nibble_count])


def generate_reverse_ipv6(hosts):
    """Build the IPv6 reverse zone file for fd00::/64."""
    lines = [soa_header()]
    lines.append("; PTR records (nibble-reversed)")
    for h in hosts:
        if h["ipv6"]:
            host_part = ipv6_reverse_host_part(h["ipv6"])
            lines.append(
                f"{host_part}  IN  PTR  {h['hostname']}.{ZONE}."
            )
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# named.conf generation
# ---------------------------------------------------------------------------

def generate_named_conf():
    return f"""// BIND9 Split-Horizon DNS Configuration for {ZONE}

options {{
    directory "/var/cache/bind";
    listen-on port 8053 {{ any; }};
    listen-on-v6 {{ none; }};
    dnssec-validation no;
    auth-nxdomain no;
    allow-query {{ any; }};
}};

controls {{ }};

acl "internal_nets" {{
    10.0.0.0/8;
    127.0.0.0/8;
    fd00::/16;
}};

view "internal" {{
    match-clients {{ internal_nets; }};
    recursion yes;
    allow-recursion {{ internal_nets; }};

    zone "{ZONE}" {{
        type master;
        file "{ZONES_DIR_INT}/db.{ZONE}";
        allow-transfer {{ 10.0.1.2; }};
    }};

    zone "{IPV4_REVERSE_ZONE}" {{
        type master;
        file "{ZONES_DIR_INT}/db.10.0.1";
        allow-transfer {{ 10.0.1.2; }};
    }};

    zone "{IPV6_REVERSE_ZONE}" {{
        type master;
        file "{ZONES_DIR_INT}/db.fd00";
        allow-transfer {{ 10.0.1.2; }};
    }};
}};

view "external" {{
    match-clients {{ any; }};
    recursion no;

    zone "{ZONE}" {{
        type master;
        file "{ZONES_DIR_EXT}/db.{ZONE}";
        allow-transfer {{ none; }};
    }};
}};
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    hosts = read_hosts(HOSTS_CSV)
    services = read_services(SERVICES_CSV)

    # Create zone directories
    os.makedirs(ZONES_DIR_INT, exist_ok=True)
    os.makedirs(ZONES_DIR_EXT, exist_ok=True)

    # Write zone files
    with open(f"{ZONES_DIR_INT}/db.{ZONE}", "w") as f:
        f.write(generate_forward_zone(hosts, services, "internal"))

    with open(f"{ZONES_DIR_EXT}/db.{ZONE}", "w") as f:
        f.write(generate_forward_zone(hosts, services, "external"))

    with open(f"{ZONES_DIR_INT}/db.10.0.1", "w") as f:
        f.write(generate_reverse_ipv4(hosts))

    with open(f"{ZONES_DIR_INT}/db.fd00", "w") as f:
        f.write(generate_reverse_ipv6(hosts))

    # Write named.conf
    with open(NAMED_CONF, "w") as f:
        f.write(generate_named_conf())

    # Set ownership so BIND (running as bind:bind) can read the files
    subprocess.run(["chown", "-R", "bind:bind", ZONES_DIR_INT], check=True)
    subprocess.run(["chown", "-R", "bind:bind", ZONES_DIR_EXT], check=True)
    subprocess.run(["chmod", "-R", "755", "/etc/bind/zones"], check=True)

    print("DNS configuration and zone files generated successfully.")


if __name__ == "__main__":
    main()
