A small-office OpenWrt router managing a segmented network (LAN, DMZ, Guest, IoT, WAN) is experiencing multiple failures after misconfiguration. The following incident tickets are open:

**INC-1: Guest Wi-Fi users cannot access the internet.** Guests on VLAN 30 receive DHCP leases but cannot browse. One user reported being able to ping the LAN gateway (192.168.1.1), which should be impossible under proper guest zone isolation.

**INC-2: IoT devices offline — no DHCP, no management.** Devices on VLAN 50 are not obtaining addresses. LAN users also cannot reach IoT device web UIs (port 8080) despite management traffic rules being present in the firewall config. A separate security review flagged that the IoT zone's router-facing input policy may be overly permissive.

**INC-3: DNS resolution broken.** DNS queries via the dnsmasq-to-stubby DNS-over-TLS chain are failing. The forwarding ports between dnsmasq and stubby appear inconsistent — both the IPv4 and IPv6 forwarding paths need to be verified end-to-end against what stubby is actually listening on.

**INC-4: HTTPS port forward broken after server migration.** The office web server was relocated from LAN (old address: 192.168.30.100) to the DMZ zone. External HTTPS access no longer works. An HTTP port forward for the same server has never been created.

**INC-5: DMZ zone not implemented.** The DMZ (VLAN 20) was planned but never built. It requires a VLAN trunk on lan2 (tagged DMZ traffic coexisting with untagged LAN on the same physical link), its own network interface, a locked-down firewall zone preventing lateral movement to internal networks, inbound port forwards for HTTP and HTTPS, a DHCP pool, and DNS/DHCP traffic rules allowing DMZ hosts to reach the router.

The architecture specification is at `/app/network_design.txt`. Configuration files:
- `/app/etc/config/network` — DSA bridge-VLAN and interface config
- `/app/etc/config/firewall` — zones, forwarding, rules, port forwards
- `/app/etc/config/dhcp` — dnsmasq and DHCP pools
- `/app/etc/stubby/stubby.yml` — DNS-over-TLS proxy

Diagnose all root causes and fix every misconfiguration. There are additional bugs beyond what the incidents describe — including security vulnerabilities and cross-subsystem inconsistencies that don't produce user-visible symptoms. Some incidents have multiple compounding root causes across different config files. The DMZ zone must be fully designed and implemented per the architecture document. All fixes must be made in-place.