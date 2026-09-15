A fleet compliance automation project at `/app/project/` is non-functional. It was designed to audit server capacity, validate host compliance, and generate compliance reports for a multi-datacenter fleet using Ansible. The project relies on four types of custom plugins — an inventory plugin, filter plugins, a validation module, and an audit callback — along with two roles, three playbooks, and vault-encrypted credentials.

Data sources: fleet inventory at `/app/fleet_inventory.json`, compliance policies at `/app/compliance_policies.yml`, and vault-encrypted credentials at `/app/seed_vault.yml`.

The project specification with expected behaviors, plugin APIs, and reference values is at `/app/fleet_spec.md`.

Repair the project so that all of the following succeed:

- `cd /app/project && ansible-inventory -i fleet_inventory.yml --list` returns correct host grouping and computed variables matching the specification's reference values
- `cd /app/project && ansible-playbook site.yml --vault-password-file vault_pass.txt` completes successfully: applies system configuration from both roles, runs fleet compliance validation with the custom module, and produces `/app/project/validation_results.json` with correct per-host compliance assessments
- `cd /app/project && ansible-playbook audit_report.yml --vault-password-file vault_pass.txt` generates `/app/project/compliance_report.txt` with correct per-host metrics and masked vault credentials per the specification
- The `fleet_audit` callback plugin produces a valid JSON audit log at `/app/project/audit_log.json` after playbook execution