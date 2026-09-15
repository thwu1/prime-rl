The C project at `/app/` implements an InChI chemical identifier processing pipeline. It uses CMake and has three operational modes:

- `inchi_pipeline --keys`: Read InChI strings from stdin, output 27-character InChIKeys to stdout
- `inchi_pipeline --sdf <file>`: Parse a V2000 SDF file, extract InChI annotations, output tab-separated `INCHIKEY\tNAME` lines
- `inchi_pipeline --dedup <file>`: Parse an SDF file, report duplicate molecules sharing the same InChIKey

The project does not currently build. After resolving build failures, the `--keys` mode produces incorrect InChIKeys, the `--sdf` mode produces incorrect results, and the `--dedup` mode is non-functional.

**Build**: Must compile from `/app/` using:
```
mkdir -p build && cd build && cmake .. && make
```

**InChIKey format**: `XXXXXXXXXXXXXX-YYYYYYYYFV-P` — 14 characters from the major layer hash, 8 characters from the minor layer hash, flag `F` (`S` for standard InChI, `N` for non-standard), version `V` (`A` for version 1), protonation `P`. The SHA-256 implementation in `sha256.c` is correct and must not be modified.

**`--keys`**: Must handle both standard (`InChI=1S/...`) and non-standard (`InChI=1/...`) inputs.

**`--sdf`**: Must correctly parse SDF data fields to extract InChI annotations and produce correct InChIKeys for all records.

**`--dedup`**: Must implement the duplicate detection mechanism using the interface defined in `dedup.h` and report all duplicate pairs.

**Test data**: `/app/data/molecules.sdf` has 9 records (7 unique, 2 duplicates). `/app/data/inchi_list.txt` has 8 InChI strings including one non-standard entry.

**Reference values**: Water `InChI=1S/H2O/h1H2` must produce `XLYOFNOQVPJJNP-UHFFFAOYSA-N`. Standard ethanol must produce `LFQSCWFLJHTTHZ-UHFFFAOYSA-N`. Non-standard ethanol `InChI=1/C2H6O/c1-2-3/h3H,2H2,1H3` must produce `LFQSCWFLJHTTHZ-UHFFFAOYNA-N`. The `--dedup` mode must detect exactly 2 duplicate pairs.
