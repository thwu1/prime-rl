Syzkaller's syzlang DSL describes Linux kernel syscall interfaces for coverage-guided fuzzing. Description files in `/app/descriptions/` model a hardware accelerator driver across two files sharing a single namespace. The corresponding C kernel headers are in `/app/include/linux/`. Reference docs: `/app/docs/syzlang_reference.md`, `/app/docs/const_extraction.md`.

Build a multi-layer audit pipeline that validates these descriptions against the kernel headers — covering binary encoding correctness, struct layout fidelity, resource lifecycle soundness, and fuzzer reachability. Running `bash /app/validate.sh` must produce `/app/report.json` with these top-level keys:

**extracted_constants** — Object mapping each `HWACCEL_*` ioctl command macro from `/app/include/linux/hwaccel.h` to its integer value as computed from the kernel C headers. All 16 ioctl command macros.

**ioctl_mismatches** — Sorted list (by syscall name) where the syzlang `const[...]` value differs from the header-derived value. Each: `{"syscall": "<name>", "syzlang_value": <int>, "expected_value": <int>, "mismatch_fields": [...]}`. Decompose both values via `_IOC` layout (31-30=direction, 29-16=size, 15-8=type, 7-0=number); `mismatch_fields` is the sorted list of differing components.

**struct_field_audit** — Keyed by struct name (only structs with bugs). Each value: sorted list (by field name) of `{"field": "<name>", "issue": "array_size_mismatch", "syzlang_value": <int>, "c_value": <int>}`. Compare syzlang struct array dimensions against C struct array sizes parsed from the kernel header. Only report genuine layout bugs — omitted `__reserved` padding fields are standard syzlang practice, not bugs.

**resources** — Keyed by resource name. Each: `parent` (base type), `special_values` (declared literals), `producers` (sorted), `consumers` (sorted). Producers: return type matches, or `ptr[out]` struct fields, or `ptr[inout]` struct fields with explicit `(out)`. Consumers: direct args, `ptr[in]` struct fields, non-`(out)` `ptr[inout]` struct fields, through one level of pointer indirection within struct fields.

**orphan_resources** — Sorted list of resources with no producer OR no consumer.

**dead_consumers** — Sorted list of syscalls consuming a resource with no producer.

**undefined_refs** — `{"category": "flags", "name": "<name>", "referenced_by": "<struct>"}` for flag sets used in struct `flags[NAME, ...]` expressions but never defined.

**invalid_len_refs** — `{"struct": "<name>", "field": "<field>", "references": "<missing>"}` for `len[X]` where X is not a sibling field.

**unused_flags** — Sorted list of defined flag sets never referenced.

**resource_dependency_order** — Topological sort of resource names by producer dependencies (A depends on B if A's producer consumes B). Exclude unproducible resources. Alphabetical tiebreak.

**minimum_call_depth** — Keyed by syscall name. Value: minimum number of distinct preceding syscall invocations needed to make all resource inputs available. Depth 0 if no resource inputs. Value -1 if any required resource is unproducible. The count reflects the full set of unique prerequisite syscalls across all required resource production chains.