# Output Schema

For each configuration in the database, produce a JSON file at `/app/results/<config_name>_result.json` with the following structure:

```json
{
  "reachable_maps": ["map_name_1", "map_name_2"],
  "eliminable_maps": ["map_name_3"],
  "reachable_programs": ["prog_name_1"],
  "eliminable_programs": ["prog_name_2"]
}
```

## Fields

- **reachable_maps**: Sorted array of map names that are referenced by at least one instruction on a live code path, considering transitive tail-call reachability from the entry program.

- **eliminable_maps**: Sorted array of map names not referenced by any live code path.

- **reachable_programs**: Sorted array of program names reachable from the entry program via live tail-call dispatch paths (including the entry program itself).

- **eliminable_programs**: Sorted array of program names never reached via any live tail-call dispatch.

## Data Sources

Program bytecodes and relocations are embedded in BPF ELF relocatable object files at `/app/programs/*.o`. Each file is a standard ELF64 object with machine type EM_BPF (247) containing `.text`, `.rela.text`, `.symtab`, and `.strtab` sections. Relocation entries in `.rela.text` reference map symbols defined in the symbol table.

Map definitions, program metadata (entry point flag, tail-call indices), `.rodata` field layout, and deployment configurations are stored in the SQLite database at `/app/ebpf_programs.db`.

## Constraints

1. The union of `reachable_maps` and `eliminable_maps` must exactly equal the full set of maps in the database. No map may appear in both lists or be absent from both.

2. The union of `reachable_programs` and `eliminable_programs` must exactly equal the full set of programs in the database.

3. A map is "reachable" if any reachable instruction in any reachable program references it via a relocation.

4. The entry program is always reachable.

5. A tail-called program is reachable only if a `bpf_tail_call` instruction targeting its index is itself on a live code path.

6. Conditional branches comparing a register loaded from `.rodata` against a constant can be resolved statically using the configuration values. If the branch is always taken, the fall-through is dead. If never taken, the target is dead (unless reachable via another path).

7. Conditional branches depending on runtime-only values (e.g., helper return values) cannot be resolved. Both taken and fall-through paths must be considered live.

8. All arrays must be sorted in ascending alphabetical order.
