A junior administrator configured the infrastructure services at `/app/services/` for a multi-tier web application serving the `infra.example.com` domain. The configurations contain multiple errors — some syntactic, some RFC-violating, some semantic.

Review `/app/requirements.md` for the full specification. Diagnose and fix all configuration issues across:

- **DNS (BIND9)**: `/app/services/dns/` — broken `named.conf` and zone files with RFC compliance violations
- **HAProxy**: `/app/services/haproxy/haproxy.cfg` — configuration errors preventing validation
- **Apache**: `/app/services/apache/` — virtual host configuration errors

Additionally, create from scratch:

- **IPv6 reverse DNS zone**: for the `2001:db8:1::/48` prefix, with PTR records matching the AAAA records in the forward zone
- **MariaDB setup**: `/app/services/mariadb/setup.sql` per the schema and access control requirements in the requirements document
- **Ansible playbook**: `/app/services/ansible/deploy.yml` automating deployment of all services with handlers, variables, and idempotent tasks

Validation tools are installed: `named-checkzone`, `named-checkconf`, `haproxy`. All configurations must be syntactically valid and semantically correct per relevant RFCs.