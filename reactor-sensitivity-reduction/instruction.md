Using Cantera with GRI-Mech 3.0 (`gri30.yaml`, bundled with Cantera), perform ignition-delay sensitivity analysis and derive a reduced combustion mechanism for stoichiometric methane/air mixtures (air composition O2:1, N2:3.76).

Compute autoignition delay times (time of maximum dT/dt in a constant-pressure adiabatic reactor, in milliseconds) at six conditions and write to `/app/ignition_delays.json` with single-letter keys:

| Key | T (K) | P (atm) |
|-----|--------|---------|
| A   | 1200   | 1       |
| B   | 1400   | 1       |
| C   | 1600   | 1       |
| D   | 1200   | 10      |
| E   | 1400   | 10      |
| F   | 1600   | 10      |

Compute constant-pressure adiabatic flame temperatures (K) for methane/air starting at T=300 K, P=1 atm at equivalence ratios 0.5, 0.7, 0.9, 1.0, and 1.2. Write to `/app/flame_temperatures.json` with string keys (e.g., "0.5").

For each of the ~325 reactions in GRI-Mech 3.0, double the rate constant and recompute the ignition delay at condition E (1400 K, 10 atm). The sensitivity coefficient is S_i = ln(tau_perturbed / tau_baseline) / ln(2). Write the top 30 reactions by descending |S_i| to `/app/ignition_sensitivity.csv` with columns: rank, reaction_index, equation, sensitivity_coefficient.

Using the sensitivity results, build a reduced mechanism with strictly fewer than 25 species that preserves essential methane/air combustion pathways. The mechanism must include at minimum: CH4, O2, H2O, N2, OH, H, O, CH3. Write the mechanism to `/app/reduced_mechanism.yaml` (loadable by Cantera) and species/reaction counts to `/app/reduced_stats.json` with keys n_species and n_reactions.

Validate the reduced mechanism against full GRI-Mech 3.0:

- Recompute ignition delays at all six conditions with the reduced mechanism. Write to `/app/validation_ignition.csv` with columns: condition, full_delay_ms, reduced_delay_ms, relative_error_percent. All relative errors must be below 30%.
- Recompute adiabatic flame temperatures at all five equivalence ratios with the reduced mechanism. Write to `/app/validation_flame.csv` with columns: equivalence_ratio, full_temp_K, reduced_temp_K, absolute_error_K. All absolute errors must be below 100 K.