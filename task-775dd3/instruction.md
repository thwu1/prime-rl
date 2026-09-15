An Apache HTTP Server (2.4.59) hosts a web application at `http://localhost`. The server uses PHP-FPM for dynamic content and mod_rewrite for URL rewriting. The server configuration contains architectural weaknesses in how different Apache modules interpret internal request structure fields and apply access controls.

A flag is stored at `/var/secret/flag.txt` (readable only by www-data). Extract the flag by exploiting the web server's configuration weaknesses through HTTP requests. The exploitation must work through the web server — not by directly reading files on disk.

Then, design a hardened virtual host configuration that eliminates the discovered attack surface while maintaining legitimate application functionality. Finally, produce a vulnerability audit report documenting the root causes.

Start services: `/app/setup.sh`
Apache config: `/usr/local/apache2/conf/` (main config and `extra/vhost.conf`)
PHP-FPM config: `/etc/php/8.3/fpm/`

## Deliverables

1. **`/app/flag.txt`** — The extracted flag value.

2. **`/app/exploit.sh`** — An executable bash script that extracts the flag via HTTP requests to `http://localhost`. Must be independently reproducible: after running `/app/setup.sh`, executing this script must re-extract the flag and either output it to stdout/stderr or write it to `/app/flag.txt`.

3. **`/app/hardened_vhost.conf`** — A replacement VirtualHost configuration for `extra/vhost.conf` that satisfies all of the following:
   - Eliminates the confusion attack primitives used in your exploit (the same exploit must no longer be able to extract sensitive data when this config is active)
   - Preserves HTTP 200 access to the index page at `http://localhost/`
   - Preserves PHP-FPM processing for unrestricted PHP files served from the document root
   - Maintains the access restriction on `credentials.php` (must return a non-200 response for direct requests)
   - Passes Apache syntax validation (i.e., `httpd -t` succeeds)

4. **`/app/audit_report.txt`** — A vulnerability analysis identifying:
   - Each distinct confusion attack primitive exploited and the mechanism by which it works
   - The specific Apache configuration directive(s) responsible for each vulnerability
   - The CVE identifier(s) for each vulnerability class (these are publicly disclosed CVEs)
   - How your hardened configuration mitigates each issue