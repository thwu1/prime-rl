A Cog (Replicate) model project at `/app/` has accumulated specification violations during development. A previous build attempt produced diagnostics at `/app/build_errors.log`, though the diagnostics may be incomplete or actively misleading about root causes. The complete Cog specification is at `/app/cog_reference.md`.

Violations span the configuration, runner code, type definitions, and project structure. Some issues interact — resolving one violation can surface or create another. The build log contains at least one red herring.

Fix all violations while preserving the model's intended interface (an image processing pipeline with the same parameters and output fields), and generate the project's OpenAPI schema.

## Deliverables

### 1. Fixed Project Files

- `/app/cog.yaml`: fully compliant with every rule in Section 1 of the specification; all directives consistent with each other and with the runner code
- `/app/run.py`: compliant with every rule in Section 2; all imports resolve unambiguously to correct definitions on disk
- `/app/output_types.py`: compliant with Section 3 type system constraints

### 2. OpenAPI Schema (`/app/openapi_schema.json`)

A valid OpenAPI schema generated from the corrected source files, conforming to the structure and type mapping rules defined in Sections 3 and 4 of the specification. The schema must accurately reflect the corrected project's inputs, outputs, and nested types.