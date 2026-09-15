#!/usr/bin/env python3
"""
Fix all bugs in the OpenWrt configuration files and implement the
complete DMZ zone from scratch.

BUG FIXES:
 1. network  — VLAN 50 bridge-vlan: lan4:t → lan4 (untagged)
 2. network  — guest interface device: br-lan.3 → br-lan.30
 3. network  — iot interface: proto dhcp → proto static + IP 192.168.50.1/24
 4. firewall — guest zone forward: ACCEPT → REJECT
 5. firewall — add missing guest→wan forwarding
 6. firewall — iot zone input: ACCEPT → DROP
 7. firewall — HTTPS redirect: dest lan/192.168.30.100 → dest dmz/192.168.20.10
 8. dhcp     — guest DHCP interface: 'lan' → 'guest'
 9. dhcp     — dnsmasq server port: 5354 → 5453
10. stubby   — listen port: 5353 → 5453
11. firewall — wan zone: add missing wan6 to network list
12. firewall — forwarding: reverse iot→lan back to lan→iot

DMZ DESIGN:
D1. network  — add bridge-vlan VLAN 20 with lan2:t (tagged trunk)
D2. network  — add dmz interface on br-lan.20, static, 192.168.20.1/24
D3. firewall — add dmz zone: input DROP, output ACCEPT, forward REJECT
D4. firewall — add dmz→wan and lan→dmz forwarding
D5. firewall — add HTTP redirect: WAN TCP 80 → 192.168.20.10:80
D6. firewall — add DMZ DNS and DHCP traffic rules
D7. dhcp     — add DMZ DHCP pool
"""

import re
import yaml


def fix_network():
    filepath = "/app/etc/config/network"
    with open(filepath) as f:
        content = f.read()

    # Bug 1: VLAN 50 — change lan4:t (tagged) to lan4 (untagged)
    content = content.replace("list ports 'lan4:t'", "list ports 'lan4'")

    # Bug 2: Guest — change br-lan.3 to br-lan.30
    content = content.replace("option device 'br-lan.3'", "option device 'br-lan.30'")

    # Bug 3: IoT — change proto dhcp to proto static with gateway IP
    old_iot = (
        "config interface 'iot'\n"
        "\toption device 'br-lan.50'\n"
        "\toption proto 'dhcp'"
    )
    new_iot = (
        "config interface 'iot'\n"
        "\toption device 'br-lan.50'\n"
        "\toption proto 'static'\n"
        "\tlist ipaddr '192.168.50.1/24'"
    )
    content = content.replace(old_iot, new_iot)

    # D1: Add bridge-vlan for VLAN 20 (DMZ) with lan2 tagged
    vlan20_section = (
        "\nconfig bridge-vlan\n"
        "\toption device 'br-lan'\n"
        "\toption vlan '20'\n"
        "\tlist ports 'lan2:t'\n"
    )
    content = content.replace(
        "config bridge-vlan\n\toption device 'br-lan'\n\toption vlan '30'",
        vlan20_section.lstrip("\n") +
        "\nconfig bridge-vlan\n\toption device 'br-lan'\n\toption vlan '30'"
    )

    # D2: Add DMZ interface section — insert before the guest interface
    dmz_iface = (
        "\nconfig interface 'dmz'\n"
        "\toption device 'br-lan.20'\n"
        "\toption proto 'static'\n"
        "\tlist ipaddr '192.168.20.1/24'\n"
    )
    content = content.replace(
        "config interface 'guest'",
        dmz_iface.lstrip("\n") + "\nconfig interface 'guest'"
    )

    with open(filepath, "w") as f:
        f.write(content)
    print("Fixed /app/etc/config/network (bugs 1-3, DMZ VLAN + interface)")


def fix_firewall():
    filepath = "/app/etc/config/firewall"
    with open(filepath) as f:
        content = f.read()

    # Bug 4: Guest zone forward ACCEPT → REJECT
    content = re.sub(
        r"(option name 'guest'\n\tlist network 'guest'\n\toption input 'DROP'\n"
        r"\toption output 'ACCEPT'\n\toption forward )'ACCEPT'",
        r"\1'REJECT'",
        content,
    )

    # Bug 6: IoT zone input ACCEPT → DROP
    content = re.sub(
        r"(option name 'iot'\n\tlist network 'iot'\n\toption input )'ACCEPT'",
        r"\1'DROP'",
        content,
    )

    # Bug 11: Add wan6 to wan zone's network list
    content = content.replace(
        "option name 'wan'\n\tlist network 'wan'\n\toption input",
        "option name 'wan'\n\tlist network 'wan'\n\tlist network 'wan6'\n\toption input",
    )

    # Bug 7: HTTPS redirect — change dest from 'lan' to 'dmz',
    # and dest_ip from 192.168.30.100 to 192.168.20.10
    content = content.replace(
        "option dest_ip '192.168.30.100'",
        "option dest_ip '192.168.20.10'",
    )
    content = re.sub(
        r"(option name 'HTTPS-Forward'\n"
        r"\toption src 'wan'\n"
        r"\toption src_dport '443'\n"
        r"\toption dest )'lan'",
        r"\1'dmz'",
        content,
    )

    # Bug 12: Fix reversed forwarding iot→lan to lan→iot
    content = content.replace(
        "config forwarding\n\toption src 'iot'\n\toption dest 'lan'\n",
        "config forwarding\n\toption src 'lan'\n\toption dest 'iot'\n",
    )

    # Bug 5: Add missing guest→wan forwarding
    guest_fwd = (
        "\nconfig forwarding\n"
        "\toption src 'guest'\n"
        "\toption dest 'wan'\n"
    )
    content = content.replace(
        "config forwarding\n\toption src 'lan'\n\toption dest 'wan'\n",
        "config forwarding\n\toption src 'lan'\n\toption dest 'wan'\n" + guest_fwd,
    )

    # D3: Add DMZ firewall zone
    dmz_zone = (
        "\nconfig zone\n"
        "\toption name 'dmz'\n"
        "\tlist network 'dmz'\n"
        "\toption input 'DROP'\n"
        "\toption output 'ACCEPT'\n"
        "\toption forward 'REJECT'\n"
    )
    content = content.replace(
        "\nconfig forwarding",
        dmz_zone + "\nconfig forwarding",
        1,
    )

    # D4: Add dmz→wan and lan→dmz forwarding
    dmz_forwarding = (
        "\nconfig forwarding\n"
        "\toption src 'dmz'\n"
        "\toption dest 'wan'\n"
        "\nconfig forwarding\n"
        "\toption src 'lan'\n"
        "\toption dest 'dmz'\n"
    )
    content = content.replace(
        "config forwarding\n\toption src 'lan'\n\toption dest 'iot'\n",
        "config forwarding\n\toption src 'lan'\n\toption dest 'iot'\n" + dmz_forwarding,
    )

    # D5: Add HTTP redirect for DMZ
    http_redirect = (
        "\nconfig redirect\n"
        "\toption name 'HTTP-Forward'\n"
        "\toption src 'wan'\n"
        "\toption src_dport '80'\n"
        "\toption dest 'dmz'\n"
        "\toption dest_ip '192.168.20.10'\n"
        "\toption dest_port '80'\n"
        "\toption proto 'tcp'\n"
        "\toption target 'DNAT'\n"
    )
    content = content.replace(
        "\nconfig rule\n\toption name 'Allow-WAN-Established'",
        http_redirect + "\nconfig rule\n\toption name 'Allow-WAN-Established'",
    )

    # D6: Add DMZ DNS and DHCP traffic rules
    dmz_rules = (
        "\nconfig rule\n"
        "\toption name 'Allow-DMZ-DNS'\n"
        "\toption src 'dmz'\n"
        "\toption proto 'tcp udp'\n"
        "\toption dest_port '53'\n"
        "\toption target 'ACCEPT'\n"
        "\nconfig rule\n"
        "\toption name 'Allow-DMZ-DHCP'\n"
        "\toption src 'dmz'\n"
        "\toption proto 'udp'\n"
        "\toption dest_port '67'\n"
        "\toption target 'ACCEPT'\n"
    )
    content = content.rstrip() + "\n" + dmz_rules

    with open(filepath, "w") as f:
        f.write(content)
    print("Fixed /app/etc/config/firewall (bugs 4-7, 11-12, DMZ zone + forwarding + redirects + rules)")


def fix_dhcp():
    filepath = "/app/etc/config/dhcp"
    with open(filepath) as f:
        content = f.read()

    # Bug 9: dnsmasq server port 5354 → 5453
    content = content.replace(
        "list server '127.0.0.1#5354'",
        "list server '127.0.0.1#5453'",
    )

    # Bug 8: Guest DHCP interface 'lan' → 'guest'
    old_guest = (
        "config dhcp 'guest'\n"
        "\toption interface 'lan'"
    )
    new_guest = (
        "config dhcp 'guest'\n"
        "\toption interface 'guest'"
    )
    content = content.replace(old_guest, new_guest)

    # D7: Add DMZ DHCP pool
    dmz_dhcp = (
        "\nconfig dhcp 'dmz'\n"
        "\toption interface 'dmz'\n"
        "\toption start '10'\n"
        "\toption limit '20'\n"
        "\toption leasetime '24h'\n"
    )
    content = content.rstrip() + "\n" + dmz_dhcp

    with open(filepath, "w") as f:
        f.write(content)
    print("Fixed /app/etc/config/dhcp (bugs 8-9, DMZ DHCP pool)")


def fix_stubby():
    filepath = "/app/etc/stubby/stubby.yml"
    with open(filepath) as f:
        config = yaml.safe_load(f)

    # Bug 10: listen ports 5353 → 5453
    config["listen_addresses"] = [
        addr.replace("5353", "5453") if isinstance(addr, str) else addr
        for addr in config.get("listen_addresses", [])
    ]

    with open(filepath, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print("Fixed /app/etc/stubby/stubby.yml (bug 10)")


if __name__ == "__main__":
    fix_network()
    fix_firewall()
    fix_dhcp()
    fix_stubby()
    print("\nAll bugs fixed and DMZ zone implemented successfully.")
