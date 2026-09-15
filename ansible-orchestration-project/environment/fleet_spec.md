# Fleet Compliance Engine - Specification

## Overview

This project automates fleet capacity auditing, compliance validation, and enforcement reporting using Ansible. It processes server data through four custom plugin types, enforces organizational policies via two roles, manages encrypted credentials, validates compliance state with a custom module, and generates compliance reports — all with structured audit logging via a custom callback.

## Data Sources

- Fleet inventory: `/app/fleet_inventory.json` — server specifications with resource allocations, network CIDRs, and risk scores
- Compliance policies: `/app/compliance_policies.yml` — capacity thresholds, required system groups/users, and kernel parameters
- Credentials: `/app/seed_vault.yml` — Ansible vault encrypted with password `Fl33t_0ld!`

## Custom Inventory Plugin

The inventory plugin (`plugins/inventory/fleet.py`) reads the fleet JSON file and populates the Ansible inventory:

- Creates groups based on each host's `datacenter`, `role`, and a compound `{datacenter}_{role}` identifier
- Excludes any host with `status: "decommissioned"`
- Sets `ansible_connection: local` for all hosts
- Computes per-host variables:
  - `capacity_utilization`: a weighted composite percentage derived from CPU, memory, and disk allocation ratios (the three resource weights sum to 100 and are not all equal)
  - `usable_hosts`: number of assignable IP addresses in the host's network CIDR (excluding network and broadcast addresses)

Plugin configuration file: `fleet_inventory.yml`

## Custom Filter Plugins

Five Jinja2 filters in `plugins/filter/compliance_filters.py`:

- `risk_grade`: maps a numeric risk score to a letter grade using uniform 20-point bands (0-20 inclusive maps to A, 21-40 to B, 41-60 to C, 61-80 to D, 81+ to F)
- `capacity_status`: maps a utilization percentage to a traffic-light label using the `capacity_warning` and `capacity_critical` thresholds defined in the compliance policies
- `cidr_host_count`: returns the number of usable host addresses for a given CIDR notation string
- `mask_credential`: partially redacts a string for safe display — for inputs longer than 5 characters, shows the first 3 and last 2 characters with asterisks between; inputs of 5 or fewer characters are fully masked with asterisks
- `sha256_digest`: returns the hex SHA-256 digest of an input string

## Custom Validation Module

The project includes a custom Ansible module `fleet_validate` at `plugins/modules/fleet_validate.py` for runtime host compliance validation.

Parameters:
- `fleet_file` (str, required): Path to the fleet inventory JSON file
- `hostname` (str, required): Name of the host to validate
- `risk_threshold` (int, required): Maximum acceptable risk score
- `capacity_threshold` (float, required): Maximum acceptable capacity utilization percentage
- `capacity_weights` (dict, required): Weight dictionary with keys `cpu`, `memory`, `disk` summing to 100

Return values:
- `compliant` (bool): Whether the host passes all compliance checks
- `capacity_utilization` (float): Computed capacity utilization using the same formula as the inventory plugin
- `violations` (list): List of violation description strings
- `msg` (str): Summary message

Compliance rules:
- A host is non-compliant if its capacity utilization is >= the capacity_threshold
- A host is non-compliant if its risk score is > the risk_threshold
- Decommissioned hosts must cause module failure (host not found)
- The module must support check_mode

## Audit Callback Plugin

The project includes a custom aggregate callback plugin `fleet_audit` at `plugins/callback/fleet_audit.py`.

Requirements:
- Type: aggregate (must be explicitly enabled in ansible.cfg via `callbacks_enabled`)
- Must properly inherit from Ansible's callback base class with correct class-level version, type, and name attributes
- Tracks task execution: counts successful, failed, and changed tasks
- Records a per-task log with task name, target host, status, and changed state
- Writes a JSON audit log to `/app/project/audit_log.json` at playbook completion (on stats event)

## Ansible Configuration

The `ansible.cfg` must correctly configure paths for all four plugin types: inventory plugins, filter plugins, the custom module library, and callback plugins. The fleet inventory plugin and fleet_audit callback must be explicitly enabled.

## Vault Management

The project requires a rekeyed vault file at `secrets.yml` in the project directory:

- All original credentials from `seed_vault.yml` must be preserved
- Two additional credentials must be added:
  - `backup_key: "bk-alpha-7742-omega"`
  - `deploy_token: "dpt-2024-xK9mL3nP"`
- Encrypted with new password `Fl33t_N3w!_S3cur3`, stored in `vault_pass.txt`

## Roles

### capacity_audit

Provisions system state according to the compliance policies:

- System groups and service accounts as defined in the policies
- Service account passwords derived from the vault's `db_master_password` using SHA-512 hashing
- Kernel tuning parameters written to `/etc/sysctl.d/99-fleet-tuning.conf`
- Message of the day at `/etc/motd` displaying the hostname and the vault's `api_token` processed through the `mask_credential` filter

### compliance_check

Deploys application configuration and web services:

- All five decrypted vault credentials written to `/etc/app/fleet_config.yml`
- Nginx web server configured: attempts HTTPS using TLS certificates from `/etc/ssl/fleet/` (these certificates do not exist on the system, so the attempt must fail gracefully and fall back to an HTTP-only configuration on port 8080 serving content from `/var/www/fleet/`)

## Playbooks

- `site.yml`: applies both roles to localhost with vault decryption, then runs a validation play that invokes the `fleet_validate` module for each active host using policy thresholds and the standard capacity weights, aggregates results, and writes them to `validation_results.json`
- `audit_report.yml`: reads fleet inventory JSON, computes per-host metrics using the custom filters, and writes the compliance report

## Compliance Report

The report at `compliance_report.txt` in the project directory must list each active (non-decommissioned) host with:

- Capacity utilization percentage (2 decimal places)
- Capacity status label
- Risk grade letter
- Usable network host count from CIDR

The report must also include all vault secrets displayed through the `mask_credential` filter.

## Reference Values

| Host           | Capacity % | Status | Risk Grade | Usable Hosts | Compliant | Violations |
|----------------|-----------|--------|------------|--------------|-----------|------------|
| localhost      | 76.25     | yellow | B          | 510          | true      | none       |
| db-primary     | 80.00     | red    | D          | 1022         | false     | capacity >= 80.0, risk_score > 50 |
| cache-node     | 25.00     | green  | A          | 126          | true      | none       |
| app-worker-01  | 68.75     | yellow | C          | 4094         | true      | none       |
| monitor-srv    | 50.00     | green  | A          | 14           | true      | none       |

Host `legacy-db` (status: decommissioned) must not appear in the inventory, validation results, or any reports.
