A SaaS analytics platform runs on PostgreSQL (`saas_platform` database on `127.0.0.1:5432`). The system uses a shared `saas` schema with Row-Level Security for tenant data isolation, several `SECURITY DEFINER` utility functions for cross-tenant reporting and system operations, and tiered access roles.

A prior penetration test flagged multiple interacting security vulnerabilities across the deployment, but the detailed findings were lost before remediation. Independently rediscover the vulnerabilities, evaluate their real-world severity and exploitability — including any attack chains between individual issues — and design hardening measures that remediate all discovered issues without breaking legitimate application functionality.

Produce `/app/assessment.json`: a JSON array of vulnerability entries, each containing at minimum: `id`, `title`, `severity` (critical/high/medium/low), `cwe`, `attack_vector`, `impact`, and `remediation_strategy`. Then apply your hardening directly to the running database.

After hardening, the following must still function correctly: tenant users querying their own data via RLS-enforced tables, the reporting service generating cross-tenant summaries through `saas.monthly_summary()`, backup file exports via `saas.export_backup()` for valid paths under `/backups/`, and currency formatting via `saas.format_currency()`.

**Roles:** `tenant_alpha` / `alpha_app_2024` (org 1), `tenant_beta` / `beta_app_2024` (org 2), `svc_reporting` / `rpt_svc_2024`, `dba_admin` / `dba_master_2024`. Start PostgreSQL with `/app/start.sh`.