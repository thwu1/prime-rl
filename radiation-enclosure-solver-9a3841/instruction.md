View-factor formulas are implemented in `/app/catalog/vfcalc.js` (Node.js) and documented in `/app/catalog/formulas.json`. The calculator reads a JSON object from stdin (`{"formula": "<id>", ...params}`) and writes a JSON result to stdout containing at minimum `F12`. Batch mode: pass a JSON array, receive a JSON array. Use this calculator for all view-factor evaluations.

Enclosure specification files reside in `/app/enclosures/*.json`. Each contains `name` (string), `type` (one of `rectangular_box`, `cylinder`, `concentric_spheres`), geometry dimensions, and a `surfaces` array. Each surface specifies `name`, `emissivity` (0 < e <= 1), `condition` (`"temperature"` in K or `"heatflux"` in W/m^2), and `value`.

Create `/app/radpipe.sh` -- a batch pipeline that processes every enclosure, solves the gray-diffuse radiosity problem (sigma = 5.670374419e-8 W/(m^2 K^4)), and populates `/app/results.db` (SQLite3).

**SQLite schema** (exact column names):

Table `enclosures`: `id` INTEGER PRIMARY KEY, `name` TEXT UNIQUE, `type` TEXT, `geometry` TEXT (JSON of dimensions).

Table `view_factors`: `enclosure_id` INTEGER, `surface_from` TEXT, `surface_to` TEXT, `value` REAL. PK: (enclosure_id, surface_from, surface_to).

Table `surface_results`: `enclosure_id` INTEGER, `name` TEXT, `area` REAL, `emissivity` REAL, `bc_type` TEXT, `bc_value` REAL, `radiosity` REAL, `net_heat_flux` REAL, `equilibrium_temp` REAL (NULL when not applicable). PK: (enclosure_id, name).

**Surface conventions by geometry type**:

- `rectangular_box`: axes x (`length_x`), y (`width_y`), z (`height_z`). `floor`/`ceiling` span xy, `front`/`back` span xz, `left`/`right` span yz. All planar (zero self-view factor).

- `cylinder`: `bottom`/`top` are flat end disks, `lateral` is the curved wall (concave, non-zero self-view factor). Dimensions: `radius`, `height`.

- `concentric_spheres`: `inner` sphere (convex, zero self-view), `outer` sphere (concave, non-zero self-view). Dimensions: `inner_radius`, `outer_radius`.

**Physical constraints**: view-factor rows sum to 1 (including self-view for concave surfaces), reciprocity (A_i F_{ij} = A_j F_{ji}), energy conservation (sum of A_i q_i = 0). Blackbody surfaces (e = 1) must not crash the solver.

Run: `bash /app/radpipe.sh`
