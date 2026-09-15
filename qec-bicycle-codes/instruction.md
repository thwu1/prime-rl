`/app/codes.json` defines bivariate bicycle (BB) quantum CSS codes over the group algebra F₂[Z_l × Z_m]. Each code entry provides group dimensions `l` and `m`, and two group algebra elements A and B as lists of exponent pairs `[a, b]` representing monomials x^a · y^b.

For each code, produce:

**Code parameters**: physical qubit count `n` (int), logical qubit count `k` (int), code distance `d` (int, minimum of X-distance and Z-distance). All linear algebra is over GF(2).

**Structural properties**: CSS orthogonality (`css_valid`, bool), GF(2) ranks of the X and Z check matrices (`hx_rank`, `hz_rank`, int), whether these ranks are equal (`rank_symmetric`, bool), encoding rate k/n (`encoding_rate`, float), and the weight per X-type parity check (`check_weight`, int — uniform across all checks for these codes).

**Stim circuit**: a Z-basis memory experiment with noise at physical error rate p=0.001 for each code. Save to `/app/circuits/{name}.stim`. Each circuit must include `DETECTOR` and `OBSERVABLE_INCLUDE` annotations.

**Detector error model**: extracted from each stim circuit in a format suitable for PyMatching decoding. Save to `/app/dem/{name}.dem`.

**Matching decoder**: construct a PyMatching decoder from each code's detector error model. Report the matching graph's node count (`matching_nodes`, int) and edge count (`matching_edges`, int).

Write `/app/results.json` containing an entry per code keyed by `name`, with fields: `n`, `k`, `d`, `css_valid`, `hx_rank`, `hz_rank`, `rank_symmetric`, `encoding_rate`, `check_weight`, `matching_nodes`, `matching_edges`. Include a top-level `best_encoding_rate` key (string): the `name` of the code with the highest encoding rate.

The `stim` and `pymatching` packages are available in the environment.