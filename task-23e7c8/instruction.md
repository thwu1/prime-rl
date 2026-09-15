A network dataplane uses a suite of eBPF/XDP programs that share compile-time feature configuration through a `.rodata` constant section. Programs conditionally reference BPF maps and dispatch to sub-programs via tail calls depending on feature flag values. Under a given configuration, code paths gated by disabled features become unreachable, along with any maps and sub-programs exclusively referenced from those dead paths.

The programs are stored as BPF ELF relocatable object files (EM_BPF) in `/app/programs/`. Map definitions, program metadata, rodata field layout, and deployment configurations are in the SQLite database at `/app/ebpf_programs.db`.

For each deployment configuration in the database, determine which BPF maps and programs are dead code that can be safely eliminated, and write results to `/app/results/<config_name>_result.json`.

Consult `/app/SCHEMA.md` for the output format specification.