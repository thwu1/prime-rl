# ETW SecurityTrace Bypass — Known Attack Techniques

This document catalogs known techniques for bypassing the SecurityTrace
access control mechanism in Windows ETW. Each technique has a distinct
forensic signature observable in kernel memory dumps.

---

## Technique 1: LogBuffersLost Union Overlap

**Identifier**: `log_buffers_lost_union_overlap`

The `WMI_LOGGER_CONTEXT` structure contains a documented counter field
(`LogBuffersLost`) that, due to an internal union in certain Windows
builds, shares memory with portions of the `Flags` bitfield at a
different interpretation layer. An attacker with arbitrary kernel write
access can set `LogBuffersLost` to a crafted value that, when the kernel
internally reads the overlapping `Flags` region, enables the
SecurityTrace bit (bit 14).

**Forensic Signature:**
- `LogBuffersLost` contains an abnormally large value (>= 0x4000, i.e., >= 16384)
- The `LogBuffersLost` value matches the session's `Flags` value exactly
- Legitimate sessions typically show `LogBuffersLost` values below 100
- The session was not created through documented `NtTraceControl` calls

---

## Technique 2: Direct Kernel Object Modification (DKOM)

**Identifier**: `direct_kernel_object_modification`

An attacker directly patches the `Flags` field within `WMI_LOGGER_CONTEXT`
via an arbitrary kernel read/write primitive (e.g., a vulnerable driver).
The SecurityTrace bit is toggled without going through any ETW API.

**Forensic Signature:**
- `LogBuffersLost` remains at normal levels (typically 0-100)
- `Flags` field has SecurityTrace set without any correlation to `LogBuffersLost`
- Session creation timestamp does not correlate with `EnableTrace` API calls
  in the system event log
- Other session metadata (`BufferSize`, `MaxEventSize`) may appear inconsistent
  with the session's provider configuration

---

## Technique 3: Provider Callback Hijacking

**Identifier**: `provider_callback_hijacking`

Instead of enabling SecurityTrace, the attacker replaces the ETW provider's
notification callback pointer with attacker-controlled code. Events are
intercepted at the provider registration level without needing consumer
access to a SecurityTrace-protected session.

**Forensic Signature:**
- SecurityTrace flag is **NOT** set on any suspicious session
- Provider callback function pointers resolve to addresses outside known
  kernel module ranges
- The provider's `EnabledKeywords` and `EnabledLevel` may show unexpected
  values
- No anomalous consumer entries exist

---

## Technique 4: Handle Table Manipulation

**Identifier**: `handle_table_manipulation`

The attacker duplicates or fabricates a session handle from a legitimate
PPL process's handle table, granting access to SecurityTrace-protected
events through an inherited security context.

**Forensic Signature:**
- Consumer process appears to have valid protection (non-zero `PS_PROTECTION.Level`)
- Handle values in the consumer entry are duplicated from another process
- Multiple consumer entries reference the same underlying handle with
  different access masks
- The consumer process's `ImageFileName` does not match expected PPL binaries
  for its stated protection level
