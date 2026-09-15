Five compiled eBPF ELF object files (with BTF metadata) are in `/app/samples/`. Build a tool at `/app/analyze.py` that performs static analysis on each object file and produces structured metadata reports.

Run the tool as `python3 /app/analyze.py`. It must produce one JSON report per input file at `/app/reports/<name>.json` (e.g., `simple_xdp.o` produces `simple_xdp.json`).

## Required report schema

```json
{
  "filename": "<name>.o",
  "license": "<license string from the ELF>",
  "programs": [
    {
      "name": "<function name>",
      "section": "<ELF section name>",
      "prog_type": "<derived type: xdp | kprobe | tracepoint | tc | ...>",
      "num_instructions": "<number of BPF instructions>",
      "helpers_called": ["<bpf_helper_name>", "..."],
      "has_packet_access": "<true if program accesses raw packet data>"
    }
  ],
  "maps": [
    {
      "name": "<map variable name>",
      "map_type": "<BPF_MAP_TYPE_HASH | BPF_MAP_TYPE_ARRAY | BPF_MAP_TYPE_PERF_EVENT_ARRAY | ...>",
      "key_size": "<key size in bytes>",
      "value_size": "<value size in bytes>",
      "max_entries": "<max entries>"
    }
  ]
}
```

## Requirements

- **Programs**: Identify all BPF program functions in the object file. Derive `prog_type` from the ELF section name following standard libbpf naming conventions.
- **Helpers**: Report which BPF helper functions each program calls, sorted alphabetically by name.
- **Packet access**: Determine whether each program directly accesses raw packet data (e.g., through the program context's data and data_end pointers). Only XDP and TC program types can have packet access.
- **Maps**: Extract user-defined BPF map definitions from the object file's type metadata. Exclude compiler-generated sections (`.rodata`, `.bss`, `.data`). Report each map's type, key size, value size, and max entries.
- **helpers_called** list must be sorted alphabetically.