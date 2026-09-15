Four Windows Registry hive files in `/app/evidence/` were recovered during incident response. The attacker embedded secret data fragments across these hives using anti-forensic concealment techniques designed to evade standard analysis tools.

Tools `hivexsh`, `hivexget`, `hivexml` (hivex suite), and `xxd` are available.

## Phase 1 — Forensic Recovery

Analyze each evidence hive, extract every hidden data fragment, and identify the concealment technique used per hive. Standard hivex tools may not work on all hives — you will need to reason about the binary regf format to recover all fragments.

## Phase 2 — Adversarial Hive Construction

Demonstrate mastery of the regf binary format by constructing a new, structurally valid registry hive at `/app/crafted.regf`. This hive must satisfy all of the following:

- Correct `regf` signature, valid header checksum, and at least one key/value pair parseable by `hivexml`
- The exact ASCII byte sequence `P0_h1v3_cr4ft` embedded within the hive data area (after the 4096-byte base block)
- The embedded string must NOT appear in `hivexml` output
- The concealment technique must differ from every anti-forensic method you identified in the evidence files — you cannot reuse any of the three evidence techniques

Write all results to `/app/findings.json`:

```json
{
  "fragments": {"<filename>": "<extracted_fragment>", ...},
  "techniques": {"<filename>": "<technique_description>", ...},
  "combined_flag": "<all fragments concatenated in alphabetical order by filename>",
  "crafted_technique": "<description of the novel concealment technique used in crafted.regf>"
}
```

For any evidence hive where the fragment is stored as a standard tool-accessible registry value, use `"plaintext"` as the technique description.