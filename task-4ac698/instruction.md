Build a command-line tool at `/app/bpf_analyzer.py` that performs static analysis on compiled BPF ELF object files and produces a structured JSON report to stdout.

Pre-compiled XDP BPF programs are available in `/app/programs/` for development and testing. Their corresponding C source code is in `/app/src/`.

The tool takes a single argument — the path to a BPF ELF object file (compiled with `clang -target bpf`) — and outputs a JSON object with these top-level keys:

- `filename`: basename of the input file
- `program_sections`: array of analysis results for each BPF program found in the ELF
- `maps`: array of BPF map definitions extracted from the ELF, sorted by name

Each entry in `program_sections` contains:

| Field | Description |
|---|---|
| `name` | ELF section name |
| `num_instructions` | count of logical BPF instructions |
| `helpers` | sorted unique list of BPF helper function IDs invoked |
| `helper_names` | corresponding human-readable helper names |
| `max_stack_depth` | maximum stack frame usage in bytes |
| `registers_used` | sorted unique list of BPF register numbers accessed |
| `has_backward_jumps` | whether any branch targets a lower-addressed instruction |

Each entry in `maps` contains:

| Field | Description |
|---|---|
| `name` | map symbol name |
| `type` | integer map type code |
| `type_name` | human-readable type name (e.g. `BPF_MAP_TYPE_ARRAY`) |
| `key_size` | key size in bytes |
| `value_size` | value size in bytes |
| `max_entries` | maximum number of entries |

The tool must produce correct results for arbitrary BPF ELF object files, not just the provided samples.