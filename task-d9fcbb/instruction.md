A Terraform project at `/app/` manages a multi-tier application (networking, application services, monitoring). All resources are currently tracked in a single monolithic state file (`terraform.tfstate`). The project must be decomposed into a domain-based modular architecture.

Two competing proposals for the decomposition have been submitted:
- `/app/proposals/by_type/` — organizes modules by Terraform resource type
- `/app/proposals/by_domain/` — organizes modules by operational domain

Neither proposal works as-is. The architectural requirements are documented in `/app/ARCHITECTURE.md`.

Evaluate both proposals against every requirement in `ARCHITECTURE.md` and produce a correct implementation:

- Write `/app/evaluation.json` with your structured assessment. It must contain: `proposal_a_assessment` (including a `violations` array), `proposal_b_assessment` (including a `violations` array), `selected_base` (which proposal's architecture to build from), and `selection_rationale`.

- Implement the correct modular configuration at `/app/` (root `.tf` files and `modules/` subdirectories) so that `terraform validate` succeeds and `terraform plan` shows zero resources to add or destroy. All state migration must use `moved` blocks. Each module must include input validation appropriate to its domain as specified in `ARCHITECTURE.md`.