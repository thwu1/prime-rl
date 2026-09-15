Three E3SM (Energy Exascale Earth System Model) configuration sources are at `/app/`:

- `config_compsets.xml` — Component set definitions mapping aliases to longnames
- `eamxx_namelist_defaults.xml` — EAMxx atmospheric parameter defaults with process inheritance and conditional overrides
- `test_suites.py` — Python-defined test suite specifications with inheritance

Produce two outputs by analyzing these interrelated sources.

## Output 1: `/app/e3sm_config.db`

SQLite database with tables:

- `compsets(alias TEXT PRIMARY KEY, longname TEXT)`
- `atm_processes(name TEXT PRIMARY KEY, parent TEXT, is_group INTEGER)` — from `atmosphere_processes_defaults`, capturing `inherit` attributes
- `test_suites(name TEXT PRIMARY KEY, direct_test_count INTEGER, inherits_from TEXT)` — `inherits_from` is comma-separated parent names (empty if none)

## Output 2: `/app/query_results.json`

JSON object with keys:

- `total_compsets` (int): Unique compset alias count.
- `atm_process_hierarchy` (object): Each process name mapped to its parent (or null).
- `num_atm_processes` (int): Process definition count.
- `constrained_params` (list): Sorted parameter names having `constraints` attributes anywhere in the namelist defaults.
- `suite_resolved_counts` (object): For `e3sm_developer`, `e3sm_integration`, and `fates` — unique test count after fully resolving inherited tests.
- `max_inheritance_depth` (object): `{"suite": <name>, "depth": <int>}` for deepest inheritance chain. Depth 0 = no parents.
- `compsets_by_bgc_mode` (object): Each BGC mode identifier mapped to sorted aliases using it.
- `compset_component_breakdown` (object): For `CRYO1850-DISMF`, `MPAS_LISIO_JRA1p5`, `WCYCLXX2010` — decompose longname into `longname`, `time`, and component slots (`atm`, `lnd`, `ice`, `ocn`, `rof`, `glc`, `wav`, `bgc` if present), each as `{"model": <str>, "physics": <str or null>}`.
- `eamxx_default_pipeline` (str): Unconditional default `atm_procs_list` from the `eamxx` process definition.
- `physics_pipeline_variants` (object): All `atm_procs_list` variants from the `physics` process definition. Keys are COMPSET selector patterns (`"default"` for unconditional).
- `grid_rad_frequencies` (object): Radiation frequency overrides from `rrtmgp`. Keys are grid patterns; prefix compset-conditional keys with `COMPSET:`.
- `cryo_compsets` (list): Sorted aliases whose sea-ice component uses delta-Eddington ice/ocean biogeochemistry (`MPASSI%DIB`).