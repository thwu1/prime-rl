The CMSIS-SVD file at `/app/device.svd` describes a microcontroller's peripheral register map. The authoritative hardware specification is at `/app/hwref.txt`. A pre-computed code generation decision manifest at `/app/proposed_codegen.json` claims to correctly analyze the SVD's write-effect bitmaps, field safety classifications, register overlaps, and peripheral inheritance.

Both the SVD and the proposed analysis contain errors. The SVD has diverged from the hardware specification in multiple ways. The proposed analysis has computational errors even relative to the SVD as given.

Produce four output files:

**`/app/fixed_device.svd`** -- The SVD corrected to match the hardware reference. Must be well-formed CMSIS-SVD XML.

**`/app/codegen_audit.json`** -- Every error in the proposed codegen manifest, evaluated against the *original* (unfixed) SVD. Each entry: `{"category": "bitmap|safety|overlap|inheritance|expansion", "location": "<peripheral.register.field>", "proposed_value": "...", "correct_value": "...", "explanation": "..."}` under an `"errors"` array.

**`/app/codegen_corrected.json`** -- Correct code generation decisions for the *fixed* SVD with keys: `bitmaps` (per-peripheral, per-register `zero_to_modify`/`one_to_modify` hex strings), `overlaps` (per-peripheral list of `{offset, registers}`), `field_safety` (keyed `Peripheral.Register.Field` -> `safe|unsafe|range(min,max)`), `derived_registers` (per-derived-peripheral list of resolved register names). Register arrays must be expanded to individual entries. Derived peripherals must have inherited registers resolved.

**`/app/hazard_assessment.json`** -- Registers in the fixed SVD containing fields with two or more distinct write-effect types from {oneToClear, oneToSet, oneToToggle, zeroToClear, zeroToSet, zeroToToggle}. Standard read-modify-write fields do not count. Each entry: `{"peripheral", "register", "write_effect_types": [sorted], "zero_to_modify", "one_to_modify"}` under `"hazardous_registers"`.

## Bitmap and safety conventions

Write-effect bitmaps follow svd2rust semantics:
- `one_to_modify`: OR of field bitmasks with oneToClear/oneToSet/oneToToggle
- `zero_to_modify`: OR of field bitmasks with zeroToClear/zeroToSet/zeroToToggle
- Register-level `modifiedWriteValues` is inherited by fields without their own override; field-level values take precedence
- Field arrays (dim/dimIncrement) expand each element's bitmask independently

Field safety (svd2rust rules):
- 1-bit field, no writeConstraint -> `safe`
- writeConstraint covering full range [0, 2^width - 1] -> `safe`
- Enumerated values covering all 2^width possibilities -> `safe`
- writeConstraint with partial range -> `range(min,max)`
- Otherwise -> `unsafe`