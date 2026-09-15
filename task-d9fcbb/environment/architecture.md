# Module Architecture Requirements

This document specifies the architectural requirements for the module decomposition.

## Req 1: Domain Cohesion
Each module must encapsulate exactly one operational domain. The three operational domains are:
- **networking**: network topology and connectivity (VPC config, subnets)
- **application**: service configuration and lifecycle (app configs, health checks, deployment metadata, manifests)
- **monitoring**: observability and alerting (alert rules, alert notification channels)

Resources must be grouped by the domain they serve, not by their Terraform resource type.

## Req 2: Input Validation
Every module must validate its inputs with domain-appropriate rules:
- `environment` must be one of: production, staging, development
- Network CIDRs must be valid IPv4 CIDR notation
- Application ports must be in the range 1024-65535
- Alert severity must be one of: critical, warning, info

## Req 3: Acyclic Dependencies
The module dependency graph must be strictly acyclic. Acceptable dependency direction: network -> application -> monitoring. No module may depend on a downstream module.

## Req 4: Cross-Module Interfaces
Downstream modules that need upstream data must consume it through explicit module outputs passed as variables. Hardcoded values and data sources referencing other modules' internal state are not acceptable.

## Req 5: State Migration via Moved Blocks
All resource address changes from the monolithic layout to the modular layout must use `moved` blocks in HCL configuration. The `terraform state mv` CLI command must not be used.

## Req 6: Zero-Destroy Migration
After migration, `terraform plan` must show zero resources to add and zero resources to destroy.
