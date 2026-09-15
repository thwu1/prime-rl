The sparse matrix analysis pipeline at `/app/sparse_pipeline.py` uses a C shared library (`/app/lib/libsparse.so`, built from source at `/app/src/`) via Python ctypes for CSR and ELLPACK SpMV kernels and structural metric computations. Python handles JDS format conversion, Reverse Cuthill-McKee reordering, and format recommendation scoring. The pipeline reads CSR matrices from `/app/data/`, converts to JDS and ELLPACK representations, computes SpMV in each format, applies RCM bandwidth reduction, computes bandwidth and profile metrics, and generates a ranking report.

The pipeline produces incorrect results across multiple subsystems. Defects exist in both the C library source and the Python orchestrator. The C source and build system are at `/app/src/` and `/app/Makefile`. Input format documentation is in `/app/FORMAT.md`.

Investigate and fix all defects so the corrected pipeline satisfies:

- All SpMV results (CSR, JDS, ELLPACK, and RCM-reordered JDS) agree within 1e-5 tolerance
- Bandwidth and profile metrics are accurate for both original and RCM-reordered matrices
- The format recommendation produces rankings consistent with each format's relative strengths given the matrix's row-length distribution
- All reported metadata (permutations, column-start offsets) is correct

Invoke the tool as:

    python3 /app/sparse_pipeline.py <data_dir> <output.json>