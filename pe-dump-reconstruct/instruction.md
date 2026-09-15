`/app/samples/` contains two files:

- `memory_dump.bin` — a raw virtual memory image of a stripped 64-bit Windows PE executable (MinGW cross-compiled, x86-64). This is the full `SizeOfImage` region as it would appear in a process's virtual address space after OS loading.
- `dump_meta.json` — contains the `load_address` at which the PE was mapped into virtual memory.

The PE's `ImageBase` field in the Optional Header still reflects the **original preferred base address**, not the actual load address from `dump_meta.json`.

Binary analysis tools (`radare2`, `x86_64-w64-mingw32-objdump`) are installed.

## Required Outputs

### `/app/output/reconstructed.exe`

The original on-disk PE file, byte-for-byte identical to the executable before it was loaded into memory. Verified by SHA-256 hash comparison.

### `/app/output/pe_report.json`

Structural analysis of the reconstructed PE in this exact schema:

```json
{
  "machine": "0x8664",
  "number_of_sections": "<int>",
  "entry_point_rva": "<hex>",
  "image_base": "<hex>",
  "section_alignment": "<hex>",
  "file_alignment": "<hex>",
  "size_of_image": "<hex>",
  "size_of_headers": "<hex>",
  "sections": [
    {
      "name": "<string>",
      "virtual_address": "<hex>",
      "virtual_size": "<hex>",
      "raw_data_size": "<hex>",
      "raw_data_pointer": "<hex>",
      "characteristics": "<hex 8-digit>"
    }
  ],
  "imports": [{"dll": "<string>", "functions": ["<string>"]}],
  "relocation_entries": "<int>"
}
```

Hex values: `0x` prefix, lowercase, no leading zeros (except `characteristics`: always 8 hex digits). `relocation_entries` counts non-padding entries only (type != 0).

### `/app/output/objdump_disasm.txt`

Full disassembly of executable sections from `x86_64-w64-mingw32-objdump`.

### `/app/output/r2_analysis.txt`

radare2 automated function analysis output — function listing via `afl` after full analysis.

### `/app/output/code_analysis.json`

```json
{
  "entry_point_raw_bytes": "<64 hex chars>",
  "call_instruction_count": "<int>",
  "imported_function_list": ["<DLL>:<function>"],
  "total_executable_section_bytes": "<int>"
}
```

- `entry_point_raw_bytes`: first 32 bytes at the entry point's raw file offset, lowercase hex, no prefix or spaces
- `call_instruction_count`: total `call`/`callq` instructions across all sections in the objdump disassembly
- `imported_function_list`: each import as `"DLL_NAME:function_name"` preserving original DLL case, sorted alphabetically
- `total_executable_section_bytes`: sum of `SizeOfRawData` for sections with `IMAGE_SCN_MEM_EXECUTE` (0x20000000) set