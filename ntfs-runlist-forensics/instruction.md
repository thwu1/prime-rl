A failed `ntfsresize` operation left an NTFS filesystem corrupted. A raw disk capture at `/app/disk_capture.raw` contains the NTFS boot sector and several MFT records at unknown byte offsets. Recovery parameters are in `/app/params.json`.

Two things are broken:

1. The primary MFT record (record number 0 — `$MFT`) was damaged during resize, losing extent mappings beyond the first data run
2. The boot sector's total-sectors field reflects the intended resize target rather than the original pre-resize volume size

Multiple MFT record candidates exist within the capture from varying origins and conditions. Some originate from different filesystems, some represent older snapshots with different extents. Standard structural validation — FILE signature matching, creation timestamp comparison, total cluster count verification, and physical extent overlap detection — is necessary but **not sufficient** to identify the correct repair source. At least one candidate passes all standard checks while being inconsistent with the volume's on-disk metadata in a way that demands cross-validation against other filesystem structures to detect. Selecting such a candidate would produce a structurally valid but semantically incorrect recovery.

Your task is to design a candidate evaluation methodology that goes beyond these standard checks, implement the recovery, and document your reasoning.

## Output (`/app/output/`)

- `repaired_mft_entry.bin` — Corrected 1024-byte MFT record with complete data extent mapping restored
- `repaired_boot_sector.bin` — Corrected 512-byte boot sector with original volume size
- `forensic_report.json` — JSON object containing:
  - `validation_methodology`: array of at least 4 validation criteria you designed for evaluating candidates. Each entry must have `criterion` (name), `description` (what it checks), and `rationale` (why this criterion is necessary for reliable recovery)
  - `candidate_records`: array of objects, one per MFT record found in the capture. Each with `offset` (integer byte offset in capture), `verdict` (`"accepted"` or `"rejected"`), and `reason` (string explaining the verdict referencing your designed criteria)
  - `selected_record_offset`: integer byte offset of the record chosen for repair
  - `corrupted_runlist`: `[{"lcn": <int>, "length": <int>}, ...]`
  - `correct_runlist`: `[{"lcn": <int>, "length": <int>}, ...]`
  - `repaired_highest_vcn`: integer
  - `original_volume_sectors`: integer
  - `confidence_assessment`: object with `level` (`"high"`, `"medium"`, or `"low"`) and `justification` (string explaining your confidence in the recovery)