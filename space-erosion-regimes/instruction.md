Create `/app/analyze.py` that reads `/app/config.json`, simulates landscape evolution for each scenario to geomorphic steady state, and writes results to `/app/results.json`.

Each scenario specifies: grid dimensions (`grid_rows`, `grid_cols`, `grid_spacing`), `random_seed`, `topo_scale`, SPACE model parameters (`K_sed`, `K_br`, `F_f`, `phi`, `H_star`, `v_s`, `m_sp`, `n_sp`, `sp_crit_sed`, `sp_crit_br`), `uplift_rate`, `dt`, `initial_soil_depth`, and `max_iterations`.

**Grid**: Raster model grid. Initial topographic elevation at each node: `y/topo_scale + x/topo_scale + noise/10000` where noise is generated via `np.random.seed(random_seed); np.random.rand(n_nodes)`. All four grid edges closed; node 0 (lower-left corner) is the sole open watershed outlet. Soil depth initialized uniformly at `initial_soil_depth`. Bedrock elevation equals initial topographic elevation; topographic elevation equals bedrock plus soil depth.

The landscape evolves under fluvial erosion governed by the SPACE (Stream Power with Alluvium Conservation and Entrainment) model with concurrent uniform tectonic uplift at `uplift_rate` applied to core node bedrock each timestep. Run for `max_iterations` steps of duration `dt`. The physical constraint that topographic elevation equals bedrock plus soil depth must hold throughout.

**Output** (`/app/results.json`): a JSON object keyed by scenario name. Each scenario contains:

- `regime` (string): `"detachment_limited"`, `"transport_limited"`, or `"bedrock_alluvial"` — classify from the scenario's physical parameters.
- `core_node_slopes` (array of float): steepest-descent slope at each core node, ordered by ascending node ID.
- `core_node_drainage_areas` (array of float): drainage area at each core node.
- `core_node_soil_depths` (array of float): soil depth at each core node.
- `core_node_sediment_fluxes` (array of float): sediment flux at each core node.
- `analytical_slopes` (array of float): steady-state slope predicted by the SPACE governing equations for the classified regime, evaluated at each core node's drainage area.
- `analytical_soil_depth` (float or null): equilibrium soil depth for the bedrock-alluvial regime; `null` otherwise.
- `analytical_sediment_fluxes` (array of float or null): steady-state sediment flux per core node for the transport-limited regime; `null` otherwise.
- `slope_area_concavity` (float): concavity index θ characterizing the power-law slope-area scaling S ∝ A^(−θ), fit to core node data.

Run: `python3 /app/analyze.py`

**Success criteria**: Correct regime classification for all scenarios. Analytical solutions consistent with SPACE steady-state theory. Numerical slopes converge to analytical with RMSE < 1e-4. Transport-limited sediment fluxes within 1% relative error of analytical. Bedrock-alluvial soil depths within 1e-3 absolute error of analytical equilibrium. Concavity index within 0.1 of the theoretical value for each scenario.
