A datacenter network team manages a VXLAN-EVPN leaf-spine fabric (2 spines, 4 leaves in 2 MLAG pairs) running Arista EOS. The YAML source-of-truth data model is at `/app/fabric.yaml`. Running configurations exported from the 6 switches are in `/app/configs/` (one `.cfg` file per device). A JSON Schema defining the required drift report structure is at `/app/schema/drift_report.schema.json`.

Configuration drift has occurred: the running configs have diverged from the data model in exactly 10 places across the 6 devices. Every device has at least one discrepancy.

Produce the following deliverables:

- `/app/drift_report.json` — Valid against the provided JSON Schema. Must contain exactly 10 findings with zero false positives, covering all 6 devices.
- `/app/configs_fixed/` — One corrected `.cfg` file per device with all drift remediated so each configuration matches the source-of-truth model.
- `/app/diffs/` — One `.diff` file per device (e.g. `dc1-spine1.diff`) in unified diff format showing the changes between the original and corrected configuration.