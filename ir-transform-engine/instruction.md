Implement `/app/irtool.py` — a peripheral register compiler for the embassy-rs/chiptool IR ecosystem.

`/app/peripheral.yaml` contains a DMA controller described in chiptool IR format — a flat YAML file with `block/`, `fieldset/`, and `enum/` prefixed keys using `::` namespaced paths (see `/app/ir_reference.md` for the full data model). The peripheral has deliberately duplicated per-channel register, fieldset, and enum definitions.

`/app/transforms.yaml` specifies an ordered pipeline of operations to consolidate and restructure the IR. Each entry maps a transform type name to its regex-based parameters (patterns use `$N` capture group references).

Your tool must apply the transform pipeline in sequence and produce three outputs:

1. `/app/output.yaml` — the resulting IR in the same chiptool prefixed-key YAML format.

2. `/app/addrmap.csv` — flat register address map (columns: `path,address,access,bit_size`) listing every leaf register with its absolute byte address. Arrays are expanded into individual indexed entries. Path format: `root_block.item[index].sub_item`. Default access is `ReadWrite`, default bit_size is `32`.

3. `/app/registers.h` — C header with hardware register access macros that must compile cleanly under `gcc -fsyntax-only -std=c11 /app/registers.h`. For every register item, define `<PFX>_<REG>_OFFSET` (hex byte offset within containing block). For array items, also define `<PFX>_<ITEM>_STRIDE` (hex) and `<PFX>_<ITEM>_LEN` (decimal). For each field in a register's fieldset, define `<PFX>_<REG>_<FIELD>_SHIFT` (decimal bit position) and `<PFX>_<REG>_<FIELD>_MASK` (hex positioned mask: `((1<<width)-1)<<shift`). For field arrays, also define `_STRIDE` and `_LEN`. Block naming prefix: root block's last `::` path component uppercased; sub-block items prepend the accessor item name uppercased (e.g., item `ch` referencing a sub-block adds `_CH` to prefix). All identifiers uppercase with `_` separators.

Run via: `python3 /app/irtool.py`