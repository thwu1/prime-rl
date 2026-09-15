A production Terraform deployment stored as a monolithic v4 state file at `/app/monolith.tfstate` must be reorganized into a module hierarchy. The target structure, naming conventions, and index conversion rules are defined in a custom specification at `/app/decomposition_spec.json`.

Implement a Python tool at `/app/migrate.py` that reads both files and produces:

- `/app/refactored.tfstate` — the reorganized Terraform v4 state file with all resources placed into their target modules
- `/app/moved.tf` — HCL `moved` blocks mapping every active source instance address to its new target address

The decomposition specification defines module assignments (mapping resources to target module paths by type or by specific `type.name`, with specific-resource matches taking precedence), resource renames (mapping old names to new names within target modules), and index conversions (transforming count-based integer indices into for_each string keys). Three index conversion strategies are used: direct `key_map` lookup, `key_from_attribute` (reading from instance attributes), and `key_from_tag` with `key_pattern` (regex extraction from a tag value).

The source state contains production edge cases that the specification does not explicitly document. Your engine must discover and correctly handle all Terraform v4 state internals — including deposed instances, tainted status markers, resource-level `depends_on` cross-references, provider alias configurations, sensitive attributes, private provider data, and per-resource schema versions — to produce output that would yield zero drift under `terraform plan`.

The `moved.tf` output must use correct HCL bracket syntax: integer indices for count-based source addresses, quoted string keys for for_each target addresses.

Run your tool: `python3 /app/migrate.py`