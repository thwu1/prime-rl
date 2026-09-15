# Network Redesign Notes — CR-2024-047
## Previous Admin (J. Miller) — Last Updated 2024-03-15

## Implementation Status

### Completed
- Backup WAN configured on eth2 with LTE modem CGNAT addressing. Tested ping to 1.1.1.1 through backup path — responds fine.
- HQ WireGuard peer added to vpn_hq. Set AllowedIPs to 0.0.0.0/0 to ensure comprehensive routing coverage so all HQ-destined traffic will match regardless of future destination subnet changes on the HQ side.
- Commercial VPN tunnel (vpn_ext) created with WireGuard. Used a temporary placeholder key for initial structural testing — the production key should be swapped in once the VPN provider confirms the account is active. Current key works for config validation purposes.
- All three new firewall zones created (wan_backup, vpn_hq, vpn_ext). Enabled masquerade on vpn_hq as a safety measure to prevent potential routing asymmetry if HQ ever changes their network topology.
- Policy routing tables 100 and 200 configured with ip rules. Corp→HQ routing verified with traceroute through tunnel.
- IoT outbound restrictions deployed with fail-safe ordering: reject-all rule placed first to ensure no traffic leaks during the brief window while subsequent allow rules are being processed by nftables.
- Guest DNS redirect configured to intercept port 53 traffic and prevent DNS leaks through VPN tunnel.
- IPv6 ULA enabled on IoT and guest VLANs for future smart-device mDNS discovery and captive-portal IPv6 support.

### Known Items (Low Priority)
- WAN ingress rate limiting not yet configured — waiting on security team to confirm threshold and protocol scope
- IoT DNS redirect deferred to phase 2 — IoT firmware typically hardcodes the gateway as DNS resolver anyway
- Guest→WAN forwarding intentionally preserved as safety net until VPN tunnel stability is confirmed over a 30-day observation period. Will remove in CR-2024-048.

### Architecture Decisions
- Used fc00::/48 as ULA prefix per RFC 4193 private address block recommendation
- vpn_ext zone configured without masquerade since WireGuard performs address translation internally at the tunnel layer — adding masquerade would double-NAT the traffic
- wan_backup zone created but network interface binding deferred until the USB-LTE adapter hardware is physically installed and the kernel module is loaded
