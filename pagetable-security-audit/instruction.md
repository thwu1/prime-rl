A physical memory dump from a crashed x86-64 system is at `/app/forensics/`. The dump contains page table structures from multiple address spaces -- some are stale remnants and one was active at crash time. The active PML4 base (CR3) was lost when the crash handler overwrote registers before they could be saved.

Analyze the provided artifacts to produce a complete forensic assessment and hardened memory image. Write all outputs to `/app/output/`.

## Provided

- `/app/forensics/memory.bin` -- raw physical memory (byte offset N = physical address N)
- `/app/forensics/crash_report.log` -- crash diagnostics: page fault details, integrity alerts, partial register state (including EFER/CR0 flags), and verified reference mappings
- `/app/forensics/kernel.elf` -- kernel ELF binary whose section and program headers encode the expected kernel virtual memory layout and permissions
- `/app/forensics/security_policy.txt` -- W^X hardening policy specifying remediation rules and security posture metric definitions

## Required Outputs

**cr3.json** -- `{"cr3": <integer>}` with the physical address of the active PML4.

**corruptions.json** -- all corrupted page table entries found, sorted by `byte_offset`:
```json
[{"byte_offset": <int>, "corrupted_value": "0x...", "corrected_value": "0x...", "virtual_address": "0x...", "corruption_type": "<type>"}]
```
`corruption_type`: `"nx_injected"` | `"present_cleared"` | `"address_bitflip"` | `"unauthorized_mapping"`.
Hex strings: lowercase, `0x` prefix, 16-digit zero-padded.

**repaired.bin** -- corrected copy of `memory.bin` with all corrupted entries fixed to their intended values.

**audit.json** -- W^X violations in the **repaired** state (pages that are both writable AND executable), sorted by virtual address (unsigned):
```json
[{"virtual_address": "0x...", "physical_address": "0x...", "page_size": <int>, "writable": true, "executable": true, "user_accessible": <bool>}]
```

**hardened.bin** -- copy of `repaired.bin` with all W^X violations eliminated per the security policy.

**posture.json** -- security posture comparison across all three states (corrupted, repaired, hardened):
```json
{
  "corrupted": {"wx_violations": <int>, "privilege_escalation_paths": <int>, "unmapped_critical_pages": <int>},
  "repaired": {"wx_violations": <int>, "privilege_escalation_paths": <int>, "unmapped_critical_pages": <int>},
  "hardened": {"wx_violations": <int>, "privilege_escalation_paths": <int>, "unmapped_critical_pages": <int>},
  "remediation": [
    {"virtual_address": "0x...", "original_permissions": "RWX", "hardened_permissions": "<R-X|RW-|R-->", "method": "<nx_set|large_page_demotion>"}
  ]
}
```
`remediation` sorted by virtual address (unsigned). Metric definitions are in the security policy.