# SciStack PDE Simulation Stack

## Root Specifications
- `scisolver +mpi`
- `scifft +mpi precision=double`

## Package Architecture

### scibase (exists — no changes needed)
Foundation library. All stack components require scibase 1.2 or later.

### scicomm (exists — no changes needed)
Communication library implementing scimpi specification versions up to 2.0.

### scicomm-ng (does not exist — must be created)
Next-generation communication library implementing scimpi specification version 3.1.
- Versions: 2.1.0, 2.0.0
- Supports optional threading
- Requires scibase 1.2+

### scilinalg (exists — incomplete)
Linear algebra library. The solver stack needs it to support distributed computation via scimpi and configurable floating-point precision (single, double, quad).

### scifft (exists — complete)
FFT library with MPI and precision support.

### scisolver (does not exist — must be created)
PDE solver framework.
- Versions: 5.2.0, 5.0.0
- MPI mode (default on): requires MPI-enabled linear algebra and FFT at double precision, plus scimpi version 3+
- Debug mode (default off)
- Non-MPI mode: still requires double-precision linear algebra and FFT
- Requires scibase 1.2+

## Environment
Use unified concretization at `/app/env` with the `/app/repo` repository.
