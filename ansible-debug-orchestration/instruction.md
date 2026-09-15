An Ansible automation project at `/app/` manages local system configuration through a custom role with filter plugins, vault-encrypted secrets, Jinja2 templates, user management, system reporting, and scheduled tasks. The project was left incomplete by a previous engineer — it has missing infrastructure components, architectural design flaws in its variable precedence strategy, and interrelated configuration bugs.

Make `ansible-playbook /app/site.yml` complete successfully and produce the correct system state:

- `/etc/nginx/conf.d/app.conf` contains a valid nginx config with a weighted upstream block where each enabled service entry includes `weight=N` derived from its `weight` attribute in group variables, the correct `server_name` from the `app_server_name` group variable, an HTTPS redirect block controlled by `ssl_redirect`, and a `proxy_set_header X-Max-Conn` reflecting the role's intentional hardened value of 500
- `/etc/app_config.json` is valid JSON with `port` set to `3000` (from `group_vars/all.yml`), `max_connections` set to `500` (from role vars — this is an intentional security override that must be preserved), vault-decrypted database credentials, and a `health_endpoints` object mapping each enabled service name to its health check URL in the form `http://127.0.0.1:PORT/health`
- Users `appuser1` and `appuser2` exist in the `appteam` group with password hashes derived from vault secrets
- `/var/log/system_report.txt` contains system facts including the `admin_email` from vault secrets, with `APP_PORT=3000`
- A cron job for `appuser1` is configured for log rotation
- The vault file `/app/secrets.yml` is decryptable using the password in `/app/vault_pass.txt`

The Jinja2 templates reference custom Ansible filter plugins that were never implemented — the `/app/filter_plugins/` directory exists but is empty. The role's `vars/main.yml` contains a documented mix of intentional security hardening overrides and an accidental variable shadowing bug; evaluate each variable's purpose individually rather than blanket-removing the file. A vault password hint exists at `/app/.vault_hint`.