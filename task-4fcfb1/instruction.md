Implement a Gaussian basis function rotation library for quantum chemistry at `/app/gauss_basis/` and produce `/app/results.json` by running the provided driver `/app/run_pipeline.py`.

In quantum chemistry, molecular orbital (MO) coefficients are expressed in Gaussian basis sets that come in two representations: Cartesian (x^i y^j z^k with i+j+k=l) and spherical/pure (real solid harmonics with 2l+1 components). Rotating MO coefficients under a spatial rotation requires constructing appropriate rotation matrices in both representations, linked via a Cartesian-to-spherical transformation.

The project skeleton at `/app/` contains `/app/config.json` (test rotation matrices and angular momenta l=1..4) and `/app/run_pipeline.py` (driver importing your module). Implement the `gauss_basis` Python package exporting these five functions:

- `cartesian_powers(l)` — Sorted tuples (i,j,k) with i+j+k=l, descending in i then j.

- `overlap_matrix(l)` — The overlap matrix S between normalized Cartesian Gaussians of angular momentum l. Element is zero unless all pairwise axis sums are even.

- `cartesian_rotation_matrix(l, R)` — The N_cart x N_cart matrix transforming normalized Cartesian Gaussian coefficients under 3x3 rotation R. The core algorithm iterates over power index arrays and sums over unique permutations (as in std::next_permutation), but the raw result operates in the unnormalized monomial basis and must be converted to the normalized Gaussian basis via a similarity transform using normalization weights derived from the self-overlap of each Cartesian component.

- `spherical_to_cartesian_matrix(l)` — The (2l+1) x N_cart matrix c mapping Cartesian to spherical coefficients, built from the real solid harmonics expressed as Cartesian polynomials, ordered by m=-l..l. The solid harmonic coefficients must also be converted from the unnormalized monomial basis to the normalized Gaussian basis before row normalization. Normalized so that c S c^T = I.

- `spherical_rotation_matrix(l, R, c, S)` — The spherical rotation matrix D = c S R_cart c^T, derived from the defining relation R_cart c^T = c^T D (left-multiply by c S and use c S c^T = I).

All functions return numpy arrays. Examine `/app/run_pipeline.py` for the exact interface. Run `python3 /app/run_pipeline.py` to generate `/app/results.json`.