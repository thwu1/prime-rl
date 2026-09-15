Three MCNP criticality safety benchmark input decks from the ICSBEP handbook are at `/app/benchmarks/` (HEU-MET-FAST-001, HEU-MET-FAST-003, PU-MET-FAST-001). Reference OpenMC XML model files for a different benchmark type (HEU-SOL-THERM-001) are at `/app/reference/heu-sol-therm-001/`. The ICSBEP experimental uncertainties database is at `/app/data/uncertainties.csv` (headerless CSV: benchmark, case, keff, uncertainty). Output format specification: `/app/spec.json`.

Produce:
- OpenMC XML model files (geometry.xml, materials.xml, settings.xml) for each benchmark under `/app/output/openmc/<benchmark-id>/`, faithfully representing the same nuclear systems as the MCNP inputs
- XML validation report at `/app/output/validation.log` (`xmlstarlet` is installed)
- Physics analysis report at `/app/output/results.json` per the spec, including material compositions, geometric characterization, fissile inventory, enrichment, and matched experimental reference data