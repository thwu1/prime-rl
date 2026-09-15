# Web Application Infrastructure — Deployment Specification

## Overview
This project provisions a multi-environment web application infrastructure using Ansible. It manages user accounts, directory structure, per-host configuration files, and system reporting across four hosts.

## Host Topology
| Host | Role | Environment | Group Path |
|------|------|-------------|------------|
| app1 | Web Server | production | webservers -> production |
| app2 | Web Server | production | webservers -> production |
| db1 | Database | production | databases -> production |
| monitor1 | Monitoring | monitoring | monitoring |

The `production` group contains `webservers` and `databases` as children.

## Vault Secrets
Encrypted with password `RedHat294!` (stored in `vault_pass.txt`):

| Variable | Value |
|----------|-------|
| vault_db_password | S3cur3P@ss2024! |
| vault_api_key | ak-7f3d9e2b1a4c8d5e |
| vault_backup_passphrase | bkp-X9mK2pL7 |

## Provisioned System State

### Users and Groups
| Entity | Type | ID | Primary Group | Shell |
|--------|------|----|---------------|-------|
| appadmin | group | GID 5000 | - | - |
| deployer | user | UID 5001 | appadmin | /bin/bash |
| svcaccount | user | UID 5002 | appadmin | /sbin/nologin |

User creation must use block/rescue error handling.

### Directory Structure
| Path | Owner | Group | Mode |
|------|-------|-------|------|
| /opt/webapp | deployer | appadmin | 2775 (setgid) |
| /opt/webapp/config | deployer | appadmin | 0755 |
| /opt/webapp/data | deployer | appadmin | 0755 |
| /opt/webapp/logs | deployer | appadmin | 0755 |

### Per-Host Configuration (`/opt/webapp/config/<hostname>.conf`)
Generated from `templates/app_config.conf.j2`:
- `[application]`: hostname, FQDN, uppercased environment name, project name
- `[paths]`: base, config, data, log directory paths
- `[database]`: only for production group hosts; includes vault_db_password
- `[monitoring]`: only for monitoring group hosts; includes vault_api_key
- `[cluster_members]`: lists all webserver hosts

### System Report
`/opt/webapp/system_report.txt` with hostname, OS distribution, kernel version, and memory information.

## Playbooks
- `site.yml`: Deploys the `site_deploy` role to all hosts, includes vault variables
- `report.yml`: Generates the system report on all hosts

## Role: site_deploy
Handles all provisioning. Must include:
- User/group management with block/rescue error handling
- Directory creation with setgid permissions
- Template-based configuration deployment
- Handler that creates a reload marker when configuration changes
