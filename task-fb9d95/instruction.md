`/app/` contains tooling for generating C11 struct definitions that are byte-compatible with WGSL (WebGPU Shading Language) memory layouts. This is used for CPU-side GPU buffer preparation, where host code must construct data buffers whose binary layout matches what the GPU shader expects byte-for-byte.

## Environment

- `/app/spec.md` — authoritative WGSL memory layout specification covering alignment, size, and stride rules for all types and both address spaces
- `/app/wgsl_parser.py` — complete and correct WGSL struct definition parser
- `/app/c_codegen.py` — partially implemented C11 code generator; unsupported types and address space combinations raise `NotImplementedError`
- `/app/reference_layouts.json` — pre-computed layout data (struct alignment, size, and per-member offset/alignment/size) for each struct in `/app/shaders/*.wgsl`, with an `address_space` field per struct indicating `"storage"` or `"uniform"` layout rules; some values deviate from the specification
- `/app/shaders/*.wgsl` — five WGSL shader files defining structs that exercise scalars, vectors, matrices, arrays, `@align`/`@size` attributes, nested struct references, and uniform address space rules

## Deliverables

### 1. Complete `/app/c_codegen.py`

Extend the code generator to support all WGSL types across both `storage` and `uniform` address spaces. The generated C11 code must produce structs whose binary layout is byte-identical to the WGSL specification for the given address space.

### 2. Correct `/app/reference_layouts.json`

Audit every value in the file against `/app/spec.md` and correct all deviations. The corrected file must retain the existing JSON structure and key names.

### 3. Create `/app/bridge.py`

A Python driver script that orchestrates the pipeline: processes all structs defined in `reference_layouts.json`, uses the code generator to produce C source files, and creates the conformance report below.

### 4. Generated C files: `/app/generated/{StructName}.c`

One C11 source file per struct in `reference_layouts.json`, named by the struct's name. Each file must:

- Compile cleanly with: `gcc -std=c11 -Wall -Werror`
- Include `static_assert` checks that verify `offsetof`, `sizeof`, and `alignof` for the struct and each member against the WGSL-specified values
- When executed, print exactly `ALL_LAYOUT_CHECKS_PASSED` to stdout and exit with code 0

### 5. Conformance report: `/app/conformance_report.json`

A JSON object documenting which structs in the original `reference_layouts.json` had correct vs. incorrect values relative to the specification.

**Schema:**

```json
{
  "<StructName>": {
    "status": "PASS or FAIL",
    "discrepancies": [
      {
        "field": "dotted.path.to.value",
        "reference": 0,
        "correct": 0
      }
    ]
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"PASS"` if all values in the original reference matched the spec for this struct; `"FAIL"` if any value differed |
| `discrepancies` | array | Each element documents one value from the **original** `reference_layouts.json` that differed from the spec-correct layout. Empty array for `"PASS"` entries. |
| `discrepancies[].field` | string | Dotted path identifying the incorrect value (e.g. `"members.direction.alignment"`, `"size"`) |
| `discrepancies[].reference` | number | The original incorrect numeric value |
| `discrepancies[].correct` | number | The spec-correct numeric value |

Every struct present in `reference_layouts.json` must have a corresponding entry in the conformance report.