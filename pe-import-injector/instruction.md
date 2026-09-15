C source files are provided at `/app/build_src/`. MinGW cross-compilers are available in the environment. Compile the following PE sample binaries into `/app/samples/`:

- `hello32.exe` — 32-bit executable from `hello32.c`
- `multi64.exe` — 64-bit executable from `multi64.c`
- `mathlib.dll` — 32-bit shared library from `mathlib.c`

Implement `/app/pe_import_editor.py` — a tool that analyzes and modifies Windows PE binary import tables. No PE parsing libraries may be used (`pefile`, `lief`, `pepy`, etc.). The tool must support three commands:

## Commands

**analyze**: `python3 /app/pe_import_editor.py analyze <pe_file>`

Print JSON to stdout:

```json
{
  "format": "PE32" or "PE32+",
  "machine": "I386" or "AMD64",
  "num_sections": 5,
  "entry_point_rva": 4096,
  "image_base": 4194304,
  "sections": [{"name": ".text", "virtual_address": 4096, "virtual_size": 512, "raw_size": 512, "raw_offset": 512}],
  "imports": {"KERNEL32.dll": ["ExitProcess", "GetStdHandle"]},
  "exports": {"dll_name": "mathlib.dll", "functions": [{"name": "add_numbers", "ordinal": 1, "rva": 4096}]}
}
```

Named imports as plain strings, ordinal-only imports as `"ordinal:N"`. Include `exports` only when the PE has exported functions. Must handle both 32-bit and 64-bit PE files.

**inject**: `python3 /app/pe_import_editor.py inject <input_pe> <output_pe> <dll_name> <func_name>`

Add a new import for the specified function from the specified DLL. All original imports must be preserved. The modified binary must be structurally valid and parseable by standard PE analysis tools. Must work for both 32-bit and 64-bit PE inputs.

**validate**: `python3 /app/pe_import_editor.py validate <pe_file>`

Cross-check the analyzer's import and export results against a PE-capable `objdump` invocation on the same file. Print `VALID` to stdout if they match. Print `MISMATCH: <details>` and exit with code 1 if they differ.