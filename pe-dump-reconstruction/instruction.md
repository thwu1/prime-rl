A PE64 executable was reflectively injected into a remote process. During incident response, the binary was captured as a raw memory dump at `/app/dump.bin`.

Supporting case files are available in `/app/`:

- `case_info.json` — forensic metadata (load address, preferred image base)
- `config_info.json` — incident responder notes on an embedded configuration
- `exports.db` — SQLite database of DLL exports observed in the target process address space
- `output_schema.json` — required JSON output format specification

Analyze the memory dump and produce the following files in `/app/analysis/`:

| File | Contents |
|------|----------|
| `header_info.json` | PE header analysis with section details |
| `relocations.json` | Parsed relocation table with computed pre-load original values |
| `imports_reconstructed.json` | Reconstructed import table with resolved function names |
| `restored.bin` | Dump binary with all loading artifacts reversed to pre-load state |
| `code_analysis.json` | Static analysis of executable code (see schema for required fields) |
| `detection.yar` | YARA rule that positively matches this dump when scanned |
| `config_decoded.json` | Decrypted embedded configuration as structured JSON |

All JSON must conform to `/app/output_schema.json`. Numeric values use `"0x..."` hex strings.