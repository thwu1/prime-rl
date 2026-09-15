A binary memory dump from a Windows kernel debugging session is at `/app/etw_dump.bin`. It contains serialized ETW (Event Tracing for Windows) session management structures extracted from the kernel's `WMI_LOGGER_CONTEXT` array and associated tables. A clean reference dump from the same system prior to compromise is at `/app/etw_clean.bin`.

An incident responder suspects an attacker used multiple techniques to consume telemetry from protected ETW providers without the required Antimalware Protected Process Light (AM-PPL) signing level. The dump may contain more than one compromised session, potentially using different bypass methods.

Reference material:
- `/app/dump_format.md` — Binary format specification (key structure offsets are missing and must be discovered)
- `/app/reference_flags.txt` — `WMI_LOGGER_CONTEXT.Flags` bitfield definitions and known protected provider GUIDs
- `/app/attack_vectors.md` — Catalog of four known SecurityTrace bypass techniques with forensic signatures

Produce two deliverables:

**1. `/app/findings.json`** — A forensic report identifying every anomalous ETW trace session, and for each one, a comparative technique analysis evaluating all four documented attack techniques and justifying the classification. The file must conform to this schema:

```json
{
  "anomalous_sessions": [
    {
      "logger_id": "<int>",
      "logger_name": "<string>",
      "flags_hex": "<hex string e.g. 0x4008>",
      "consumers": [
        {
          "pid": "<int>",
          "process_name": "<string>",
          "protection_level_hex": "<hex string e.g. 0x00>"
        }
      ],
      "providers": ["<guid-string-lowercase>"]
    }
  ],
  "security_trace_bit_position": "<int>",
  "security_trace_mask_hex": "<hex string>",
  "technique_analysis": [
    {
      "logger_id": "<int>",
      "identified_technique": "<technique identifier from attack_vectors.md>",
      "ruling_out": {
        "<other_technique_id_1>": "<evidence-based reason this technique does not match>",
        "<other_technique_id_2>": "<evidence-based reason>",
        "<other_technique_id_3>": "<evidence-based reason>"
      },
      "severity": "<critical|high|medium|low>"
    }
  ]
}
```

An anomalous session is one where the SecurityTrace flag is enabled but at least one consumer process has no process protection at all (PS_PROTECTION.Level = 0x00, meaning both Type and Signer are zero). Legitimate sessions whose consumers run at any PPL/PP level (e.g., AM-PPL 0x31, LSA-PPL 0x41) should NOT appear in the anomalous list.

For each anomalous session, `technique_analysis` must evaluate all four documented techniques from `/app/attack_vectors.md`, identify which one matches the forensic evidence, and provide specific evidence-based reasons for ruling out the other three. Different anomalous sessions may use different bypass techniques.

**2. `/app/detect_bypass.yar`** — A YARA rule that matches `/app/etw_dump.bin` and does NOT match `/app/etw_clean.bin`. The rule must include a `meta` section with a `description` field and should detect indicators of the bypass technique(s) found.