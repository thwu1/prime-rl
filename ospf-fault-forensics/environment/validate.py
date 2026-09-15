#!/usr/bin/env python3
"""
Validates corrected FRR configurations for the OSPF enterprise network.
Checks for misconfigurations that would prevent full connectivity.

Usage: python3 /app/validate.py
"""

import ipaddress
import json
import os
import re
import sys


def load_topology(path="/app/topology.json"):
    with open(path) as f:
        return json.load(f)


class FRRConfigParser:
    """Parse an FRR config file into structured data."""

    def __init__(self, config_text):
        self.raw = config_text
        self.hostname = self._parse_hostname()
        self.interfaces = self._parse_interfaces()
        self.ospf = self._parse_ospf()
        self.prefix_lists = self._parse_prefix_lists()

    def _parse_hostname(self):
        m = re.search(r"^hostname\s+(\S+)", self.raw, re.MULTILINE)
        return m.group(1) if m else None

    def _parse_interfaces(self):
        interfaces = {}
        current_iface = None
        for line in self.raw.split("\n"):
            stripped = line.strip()
            m = re.match(r"^interface\s+(\S+)", stripped)
            if m:
                current_iface = m.group(1)
                interfaces[current_iface] = {"address": None}
                continue
            if current_iface:
                if stripped == "!" or stripped == "exit":
                    current_iface = None
                    continue
                m = re.match(r"ip address\s+(\S+)", stripped)
                if m:
                    interfaces[current_iface]["address"] = m.group(1)
        return interfaces

    def _parse_ospf(self):
        ospf = {
            "router_id": None,
            "passive_default": False,
            "passive_interfaces": set(),
            "no_passive_interfaces": set(),
            "networks": [],
            "distribute_lists": [],
        }
        in_ospf = False
        brace_depth = 0
        for line in self.raw.split("\n"):
            stripped = line.strip()
            if stripped.startswith("router ospf"):
                in_ospf = True
                continue
            if in_ospf:
                if stripped == "!" or stripped.startswith("exit"):
                    in_ospf = False
                    continue
                # Skip comments
                if stripped.startswith("#") or stripped.startswith("!"):
                    continue

                m = re.match(r"ospf router-id\s+(\S+)", stripped)
                if m:
                    ospf["router_id"] = m.group(1)

                if stripped == "passive-interface default":
                    ospf["passive_default"] = True

                m = re.match(r"passive-interface\s+(\S+)", stripped)
                if m and m.group(1) != "default":
                    ospf["passive_interfaces"].add(m.group(1))

                m = re.match(r"no passive-interface\s+(\S+)", stripped)
                if m:
                    ospf["no_passive_interfaces"].add(m.group(1))

                m = re.match(r"network\s+(\S+)\s+area\s+(\S+)", stripped)
                if m:
                    ospf["networks"].append(
                        {"prefix": m.group(1), "area": m.group(2)}
                    )

                m = re.match(r"distribute-list\s+prefix\s+(\S+)\s+in", stripped)
                if m:
                    ospf["distribute_lists"].append(m.group(1))
        return ospf

    def _parse_prefix_lists(self):
        prefix_lists = {}
        for line in self.raw.split("\n"):
            stripped = line.strip()
            m = re.match(
                r"ip prefix-list\s+(\S+)\s+seq\s+(\d+)\s+(permit|deny)\s+(.+)",
                stripped,
            )
            if m:
                name = m.group(1)
                if name not in prefix_lists:
                    prefix_lists[name] = []
                prefix_lists[name].append(
                    {
                        "seq": int(m.group(2)),
                        "action": m.group(3),
                        "prefix_spec": m.group(4).strip(),
                    }
                )
        # Sort each prefix list by sequence number
        for name in prefix_lists:
            prefix_lists[name].sort(key=lambda x: x["seq"])
        return prefix_lists

    def is_interface_passive(self, iface_name):
        """Check if an interface is passive in OSPF."""
        if iface_name in self.ospf["no_passive_interfaces"]:
            return False
        if self.ospf["passive_default"]:
            return True
        if iface_name in self.ospf["passive_interfaces"]:
            return True
        return False

    def is_address_in_ospf(self, interface_address):
        """Check if an interface address is covered by an OSPF network statement.

        FRR's 'network' command matches interfaces whose IP falls within the
        specified prefix.
        """
        addr_str = interface_address.split("/")[0]
        iface_addr = ipaddress.ip_address(addr_str)
        for net in self.ospf["networks"]:
            try:
                ospf_net = ipaddress.ip_network(net["prefix"], strict=False)
                if iface_addr in ospf_net:
                    return True
            except ValueError:
                continue
        return False

    def does_distribute_list_block(self, prefix_str):
        """Check if any distribute-list would block the given prefix."""
        target = ipaddress.ip_network(prefix_str, strict=False)
        for dl_name in self.ospf["distribute_lists"]:
            if dl_name in self.prefix_lists:
                for entry in self.prefix_lists[dl_name]:
                    if self._prefix_list_entry_matches(target, entry):
                        return entry["action"] == "deny"
        return False

    def _prefix_list_entry_matches(self, target, entry):
        """Check if a target prefix matches a prefix-list entry."""
        parts = entry["prefix_spec"].split()
        try:
            pl_net = ipaddress.ip_network(parts[0], strict=False)
        except ValueError:
            return False

        le = None
        ge = None
        for i, p in enumerate(parts):
            if p == "le" and i + 1 < len(parts):
                le = int(parts[i + 1])
            if p == "ge" and i + 1 < len(parts):
                ge = int(parts[i + 1])

        target_len = target.prefixlen

        # Check if target's network address is within the prefix-list network
        if target.network_address not in pl_net and target != pl_net:
            return False

        # Check prefix length constraints
        if le is None and ge is None:
            # Exact match on prefix length
            return target_len == pl_net.prefixlen
        if ge is not None and target_len < ge:
            return False
        if le is not None and target_len > le:
            return False
        if ge is None and target_len < pl_net.prefixlen:
            return False
        return True


def validate_configs(fixed_dir, topology):
    """Validate corrected FRR configs. Returns list of error strings."""
    errors = []

    configs = {}
    for router_name in topology["routers"]:
        config_path = os.path.join(fixed_dir, f"{router_name}.conf")
        if not os.path.isfile(config_path):
            errors.append(f"Missing config file: {config_path}")
            continue
        with open(config_path) as f:
            config_text = f.read()
        configs[router_name] = FRRConfigParser(config_text)

    if errors:
        return errors

    # Check 1: Transit interfaces must not be passive
    for router_name, router_info in topology["routers"].items():
        parser = configs[router_name]
        for iface_name, iface_info in router_info["interfaces"].items():
            if iface_info.get("type") == "transit":
                if parser.is_interface_passive(iface_name):
                    errors.append(
                        f"[{router_name}] Transit interface {iface_name} "
                        f"(link to {iface_info['peer']}) is passive "
                        f"- OSPF adjacency cannot form"
                    )

    # Check 2: All interfaces must be covered by OSPF network statements
    for router_name, router_info in topology["routers"].items():
        parser = configs[router_name]
        for iface_name, iface_info in router_info["interfaces"].items():
            if iface_info.get("type") == "loopback":
                continue  # loopback not strictly required
            iface_addr = iface_info.get("address")
            if iface_addr and not parser.is_address_in_ospf(iface_addr):
                errors.append(
                    f"[{router_name}] Interface {iface_name} ({iface_addr}) "
                    f"is not covered by any OSPF network statement"
                )

    # Check 3: No distribute-list should block host or server subnets
    protected_subnets = list(topology.get("host_subnets", []))
    if "server_subnet" in topology:
        protected_subnets.append(topology["server_subnet"])

    for router_name in topology["routers"]:
        parser = configs[router_name]
        for subnet in protected_subnets:
            if parser.does_distribute_list_block(subnet):
                errors.append(
                    f"[{router_name}] Distribute-list blocks route "
                    f"to {subnet}"
                )

    return errors


def main():
    topology = load_topology()
    fixed_dir = "/app/fixed_configs"

    if not os.path.isdir(fixed_dir):
        print("ERROR: /app/fixed_configs/ directory not found")
        print("Create corrected configs at /app/fixed_configs/<router>.conf")
        sys.exit(1)

    errors = validate_configs(fixed_dir, topology)

    if errors:
        print(f"VALIDATION FAILED - {len(errors)} issue(s) found:\n")
        for e in errors:
            print(f"  [FAIL] {e}")
        sys.exit(1)
    else:
        print("VALIDATION PASSED - All configurations are correct")
        sys.exit(0)


if __name__ == "__main__":
    main()
