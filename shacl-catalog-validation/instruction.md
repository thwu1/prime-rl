An environmental data team drafted a custom DCAT-AP application profile ("SciDCAT-Env v2") with SHACL validation shapes and an RDF catalog of five environmental monitoring datasets. Both artifacts are defective — the shapes contain multiple modeling errors that cause them to silently accept invalid data or incorrectly reject valid data, and the catalog has numerous data-level defects. Neither validates correctly against the intended profile.

The full profile specification is at `/app/profile_requirements.md`. The draft shapes are at `/app/shapes_draft.ttl` and the draft catalog at `/app/catalog_draft.ttl`. Six deliberately non-compliant test catalogs are in `/app/negative_samples/`.

Produce corrected versions:

- `/app/output/shapes.ttl` — SHACL shapes that correctly enforce every requirement in the profile specification
- `/app/output/catalog.ttl` — RDF catalog that fully conforms to the corrected shapes

The corrected shapes must reject each negative sample in `/app/negative_samples/`. Do not weaken or remove constraints to work around data issues — fix the underlying data where the requirement is legitimate.