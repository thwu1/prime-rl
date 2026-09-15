The `/app/dumps/` directory contains six SBR (Serial Boot ROM) binary dumps from LSI SAS2008-based storage controller cards, plus a `manifest.json` with vendor/model/mode metadata for each. The `/app/target_spec.json` specifies the crossflash objective.

Crossflash the Fujitsu D2607 controller from MegaRAID (iMR) mode to IT/IR (HBA passthrough) mode with all 8 SAS ports enabled. Previous crossflash attempts using generic vendor SBR images left only 4 of 8 ports working — the second SFF-8087 connector was completely dead. A correct crossflash must resolve this.

No documentation of the 256-byte SBR binary format is provided. The format must be reverse-engineered from the samples by correlating binary content with manifest metadata. These dumps were collected from various sources and may vary in quality.

## Output

Produce all files in `/app/output/`:

- **`target.bin`** — 256-byte SBR binary that converts the Fujitsu D2607 to IT/IR mode with all 8 SAS ports enabled. All internal data integrity mechanisms must be valid. The Fujitsu board's unique identifiers (subsystem IDs, SAS address) and hardware-specific calibration parameters must be preserved from the original dump.

- **`target.hex`** — `xxd`-format hex dump of `target.bin` (must roundtrip exactly via `xxd -r`).

- **`diff_report.txt`** — `cmp -l` byte-level comparison between `/app/dumps/fujitsu_d2607_original.bin` and `target.bin`.

- **`field_map.json`** — `{"fields": [{"offset_hex": "0xNN", "size_bytes": N, "description": "..."}]}` documenting all reverse-engineered SBR fields and structural features discovered in the format.

- **`integrity_audit.json`** — `{"samples": [{"filename": "...", "valid": true/false, "issues": ["..."]}]}` assessing the structural integrity of every dump in `/app/dumps/` using whatever validation mechanisms exist in the format.