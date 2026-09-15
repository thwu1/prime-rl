Four RISC-V hardware configuration files in `/app/configs/` each contain multiple constraint violations as defined by the Sail RISC-V formal model — the official ISA specification maintained by RISC-V International. The Sail source files encoding these constraints are in `/app/sail_sources/` (`validate_config.sail` and `extensions.sail`).

Your task: read and comprehend the Sail source to determine the complete set of validity constraints, identify all violations in each configuration, repair each configuration to satisfy every constraint, and produce a structured audit report.

**Requirements:**

- Corrected configuration files must be written to `/app/output/` using the same filenames as the originals.
- Each corrected config must pass all constraints defined in the Sail validation logic with zero violations.
- Each corrected config must preserve the original design intent: same `xlen` value and same primary extension profile (do not disable extensions that define the configuration's purpose).
- Produce `/app/audit.json` with a per-config structured report:

```json
{
  "<filename>": {
    "violations": ["VIOLATION_ID_1", "VIOLATION_ID_2"],
    "num_violations": 2
  }
}
```

The Sail source contains all the information needed to understand the constraint rules and their interactions. Some constraints may cascade — fixing one violation may introduce or resolve others.