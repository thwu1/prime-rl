Build an executable at `/app/speciate` that performs EPA SMOKE-compatible chemical speciation on the emissions inventory in `/app/data/`.

SMOKE format and I/O API documentation is provided in `/app/docs/`. The input data files conform to these specifications. The tool must parse all input files, resolve speciation cross-references, apply pollutant conversions where applicable, compute speciated emissions, and produce all output artifacts.

**Required outputs** (created by running `/app/speciate`):

**`/app/output/speciated.csv`**

Header: `REGION_CD,SCC,POLID,SPECIES_ID,PROFILE_CODE,MASS_TONS,MOLE_AMOUNT`

- Rows sorted ascending by REGION_CD, SCC, POLID, SPECIES_ID
- Numeric fields formatted to 4 decimal places
- POLID reflects the original inventory pollutant, not any converted pollutant

**`/app/output/diagnostics.csv`**

Header: `REGION_CD,SCC,POLID,PROFILE_CODE,GSREF_SCC,GSREF_FIPS,GSREF_POLLUTANT`

- One row per inventory record documenting which cross-reference entry resolved the match
- GSREF_SCC, GSREF_FIPS, GSREF_POLLUTANT are the field values from the matched cross-reference row
- Sorted ascending by REGION_CD, SCC, POLID

**`/app/output/speciation.db`** — SQLite database containing:

- Table `inventory`: columns `region_cd TEXT, scc TEXT, polid TEXT, ann_value REAL`
- Table `speciated`: columns `region_cd TEXT, scc TEXT, polid TEXT, species_id TEXT, profile_code TEXT, mass_tons REAL, mole_amount REAL`
- Table `match_log`: columns `region_cd TEXT, scc TEXT, polid TEXT, profile_code TEXT, gsref_scc TEXT, gsref_fips TEXT, gsref_pollutant TEXT`
- Index named `idx_speciated_lookup` on `speciated(region_cd, scc, polid, species_id)`

**`/app/output/emissions.nc`** — Models-3 I/O API-conformant NetCDF file:

- Parse grid `SE_US_12KM` and its coordinate system from `/app/data/griddesc.txt`
- FTYPE=1 (GRDDED3), single layer, single timestep
- SDATE derived from inventory `#YEAR` header as YYYYDDD (year × 1000 + 1), STIME=0, TSTEP=0
- All mandatory I/O API global attributes set from the parsed GRIDDESC parameters
- VGTYP set to IMISS3, VGTOP set to BADVAL3
- VAR-LIST: sorted unique species names from speciation output, each right-padded to 16 characters
- Standard I/O API dimensions: TSTEP (unlimited), DATE-TIME (2), LAY (1), VAR (NVARS), ROW (NROWS), COL (NCOLS)
- TFLAG variable: int32 (TSTEP, VAR, DATE-TIME) with (SDATE, STIME) pairs
- One float32 variable per species with dimensions (TSTEP, LAY, ROW, COL), initialized to zero

**Constraints**:

- Exit code 0 on success
- Cross-reference resolution must follow SMOKE's specificity-based precedence where more-specific entries override less-specific ones across the SCC, geographic, and pollutant dimensions
- Apply pollutant conversion factors when the assigned profile's species are defined under a different pollutant basis than the inventory record
- Both mass-based and mole-based speciation factors from the profile must be applied
