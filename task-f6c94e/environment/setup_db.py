#!/usr/bin/env python3
"""Initialize the vulnerability database from NVD data."""

import sqlite3

db = sqlite3.connect('/app/vulndb.sqlite')
c = db.cursor()

c.execute('''CREATE TABLE cves (
    cve_id TEXT PRIMARY KEY,
    description TEXT,
    cvss_vector TEXT,
    cwe_id TEXT,
    published TEXT
)''')

c.execute('''CREATE TABLE cpe_configurations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cve_id TEXT,
    operator TEXT DEFAULT 'OR',
    FOREIGN KEY (cve_id) REFERENCES cves(cve_id)
)''')

c.execute('''CREATE TABLE cpe_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER,
    criteria TEXT,
    vulnerable INTEGER DEFAULT 1,
    version_start_including TEXT,
    version_start_excluding TEXT,
    version_end_including TEXT,
    version_end_excluding TEXT,
    FOREIGN KEY (config_id) REFERENCES cpe_configurations(id)
)''')

cves_data = [
    ("CVE-2021-44228",
     "Apache Log4j2 2.0-beta9 through 2.15.0 JNDI features do not protect against attacker controlled LDAP and other JNDI related endpoints. An attacker who can control log messages or log message parameters can execute arbitrary code loaded from LDAP servers when message lookup substitution is enabled.",
     "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:C/C:H/I:H/A:H",
     "CWE-917", "2021-12-10"),
    ("CVE-2021-45046",
     "It was found that the fix to address CVE-2021-44228 in Apache Log4j 2.15.0 was incomplete in certain non-default configurations. This could allow attackers with control over Thread Context Map data to craft malicious input data using a JNDI Lookup pattern resulting in an information leak and remote code execution in some environments and local code execution in all environments.",
     "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
     "CWE-917", "2021-12-14"),
    ("CVE-2014-6271",
     "GNU Bash through 4.3 processes trailing strings after function definitions in the values of environment variables, which allows remote attackers to execute arbitrary code via a crafted environment, as demonstrated by vectors involving the ForceCommand feature in OpenSSH sshd.",
     "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
     "CWE-78", "2014-09-24"),
    ("CVE-2021-23214",
     "When the server is configured to use trust authentication with a clientcert requirement or to use cert authentication, a man-in-the-middle attacker can inject arbitrary SQL queries when a connection is first established, despite the use of SSL certificate verification and encryption.",
     "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H",
     "CWE-295", "2021-11-11"),
    ("CVE-2014-0160",
     "The TLS and DTLS implementations in OpenSSL 1.0.1 before 1.0.1g do not properly handle Heartbeat Extension packets, which allows remote attackers to obtain sensitive information from process memory via crafted packets that trigger a buffer over-read, as demonstrated by reading private keys, aka the Heartbleed bug.",
     "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
     "CWE-125", "2014-04-07"),
    ("CVE-2021-41773",
     "A flaw was found in a change made to path normalization in Apache HTTP Server 2.4.49. An attacker could use a path traversal attack to map URLs to files outside the directories configured by Alias-like directives.",
     "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
     "CWE-22", "2021-10-05"),
    ("CVE-2016-5195",
     "Race condition in mm/gup.c in the Linux kernel 2.x through 4.x before 4.8.3 allows local users to gain privileges by leveraging incorrect handling of a copy-on-write (COW) feature to write to a read-only memory mapping, as exploited in the wild in October 2016, aka Dirty COW.",
     "CVSS:3.1/AV:L/AC:H/PR:L/UI:N/S:U/C:H/I:H/A:H",
     "CWE-362", "2016-11-10"),
    ("CVE-2020-11022",
     "In jQuery versions greater than or equal to 1.2 and before 3.5.0, passing HTML from untrusted sources even after sanitizing it to one of jQuery DOM manipulation methods may execute untrusted code.",
     "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N",
     "CWE-79", "2020-04-29"),
    ("CVE-2021-3156",
     "Sudo before 1.9.5p2 contains an off-by-one error that can result in a heap-based buffer overflow, which allows privilege escalation to root via sudoedit -s and a command-line argument that ends with a single backslash character.",
     "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
     "CWE-122", "2021-01-26"),
    ("CVE-2020-14882",
     "Vulnerability in the Oracle WebLogic Server product of Oracle Fusion Middleware. Easily exploitable vulnerability allows unauthenticated attacker with network access via HTTP to compromise Oracle WebLogic Server.",
     "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
     "CWE-74", "2020-10-21"),
]

for cve in cves_data:
    c.execute("INSERT INTO cves VALUES (?, ?, ?, ?, ?)", cve)

# CVE-2021-44228: Log4j [2.0, 2.15.0)
c.execute("INSERT INTO cpe_configurations (cve_id, operator) VALUES ('CVE-2021-44228', 'OR')")
cid = c.lastrowid
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable, version_start_including, version_end_excluding) VALUES (?, 'cpe:2.3:a:apache:log4j:*:*:*:*:*:*:*:*', 1, '2.0', '2.15.0')", (cid,))

# CVE-2021-45046: Log4j [2.0, 2.16.0)
c.execute("INSERT INTO cpe_configurations (cve_id, operator) VALUES ('CVE-2021-45046', 'OR')")
cid = c.lastrowid
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable, version_start_including, version_end_excluding) VALUES (?, 'cpe:2.3:a:apache:log4j:*:*:*:*:*:*:*:*', 1, '2.0', '2.16.0')", (cid,))

# CVE-2014-6271: Bash <= 4.3
c.execute("INSERT INTO cpe_configurations (cve_id, operator) VALUES ('CVE-2014-6271', 'OR')")
cid = c.lastrowid
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable, version_end_including) VALUES (?, 'cpe:2.3:a:gnu:bash:*:*:*:*:*:*:*:*', 1, '4.3')", (cid,))

# CVE-2021-23214: PostgreSQL [13.0, 13.5) + [12.0, 12.9) + [11.0, 11.14)
c.execute("INSERT INTO cpe_configurations (cve_id, operator) VALUES ('CVE-2021-23214', 'OR')")
cid = c.lastrowid
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable, version_start_including, version_end_excluding) VALUES (?, 'cpe:2.3:a:postgresql:postgresql:*:*:*:*:*:*:*:*', 1, '13.0', '13.5')", (cid,))
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable, version_start_including, version_end_excluding) VALUES (?, 'cpe:2.3:a:postgresql:postgresql:*:*:*:*:*:*:*:*', 1, '12.0', '12.9')", (cid,))
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable, version_start_including, version_end_excluding) VALUES (?, 'cpe:2.3:a:postgresql:postgresql:*:*:*:*:*:*:*:*', 1, '11.0', '11.14')", (cid,))

# CVE-2014-0160: OpenSSL [1.0.1, 1.0.1f]
c.execute("INSERT INTO cpe_configurations (cve_id, operator) VALUES ('CVE-2014-0160', 'OR')")
cid = c.lastrowid
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable, version_start_including, version_end_including) VALUES (?, 'cpe:2.3:a:openssl:openssl:*:*:*:*:*:*:*:*', 0, '1.0.1', '1.0.1f')", (cid,))

# CVE-2021-41773: Apache HTTP Server 2.4.49 exact
c.execute("INSERT INTO cpe_configurations (cve_id, operator) VALUES ('CVE-2021-41773', 'OR')")
cid = c.lastrowid
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable) VALUES (?, 'cpe:2.3:a:apache:http_server:2.4.49:*:*:*:*:*:*:*', 1)", (cid,))

# CVE-2016-5195: Linux kernel [2.6.22, 4.8.3)
c.execute("INSERT INTO cpe_configurations (cve_id, operator) VALUES ('CVE-2016-5195', 'OR')")
cid = c.lastrowid
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable, version_start_including, version_end_excluding) VALUES (?, 'cpe:2.3:o:linux:linux_kernel:*:*:*:*:*:*:*:*', 1, '2.6.22', '4.8.3')", (cid,))

# CVE-2020-11022: jQuery [1.2, 3.5.0)
c.execute("INSERT INTO cpe_configurations (cve_id, operator) VALUES ('CVE-2020-11022', 'OR')")
cid = c.lastrowid
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable, version_start_including, version_end_excluding) VALUES (?, 'cpe:2.3:a:jquery:jquery:*:*:*:*:*:*:*:*', 1, '1.2', '3.5.0')", (cid,))

# CVE-2021-3156: Sudo [1.8.2, 1.9.5)
c.execute("INSERT INTO cpe_configurations (cve_id, operator) VALUES ('CVE-2021-3156', 'OR')")
cid = c.lastrowid
c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable, version_start_including, version_end_excluding) VALUES (?, 'cpe:2.3:a:sudo_project:sudo:*:*:*:*:*:*:*:*', 1, '1.8.2', '1.9.5')", (cid,))

# CVE-2020-14882: WebLogic specific versions
c.execute("INSERT INTO cpe_configurations (cve_id, operator) VALUES ('CVE-2020-14882', 'OR')")
cid = c.lastrowid
for ver in ["10.3.6.0.0", "12.1.3.0.0", "12.2.1.3.0", "12.2.1.4.0", "14.1.1.0.0"]:
    c.execute("INSERT INTO cpe_matches (config_id, criteria, vulnerable) VALUES (?, ?, 1)", (cid, f"cpe:2.3:a:oracle:weblogic_server:{ver}:*:*:*:*:*:*:*"))

db.commit()
db.close()
