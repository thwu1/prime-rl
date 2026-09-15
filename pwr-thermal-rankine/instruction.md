A PWR nuclear plant has submitted a thermal-hydraulic analysis as part of a 10 CFR 50.90 license amendment request for a power uprate. The applicant's analysis is at `/app/prior_analysis.json` and the plant design specifications are in `/app/plant_specs.toml`.

The analysis covers primary-side subchannel thermal-hydraulics for a central subchannel of the 17x17 square-lattice fuel assembly and secondary-side regenerative Rankine cycle performance with one open feedwater heater.

Regulatory review has flagged this analysis as potentially containing computational errors that may overstate the plant's thermal margins. The acceptance criterion for the proposed uprate is that the peak steady-state cladding outer wall temperature must not exceed the limit specified in the plant design under uprated conditions.

Independently evaluate the applicant's analysis. Identify and correct all computational errors. Determine the maximum safe power uprate percentage consistent with the cladding temperature constraint.

Write `/app/results.json` with:

- `subchannel_hydraulic_diameter_in` — inches
- `subchannel_flow_area_in2` — in^2
- `reynolds_number`
- `fanning_friction_factor`
- `darcy_friction_factor`
- `frictional_pressure_drop_psi` — psi
- `nusselt_number`
- `heat_transfer_coefficient_W_m2K` — W/(m^2-K)
- `extraction_mass_fraction`
- `cycle_thermal_efficiency` — decimal fraction
- `cycle_heat_rate_btu_kwh` — BTU/kWh
- `max_uprate_percentage` — maximum safe power increase as percentage (e.g. 15.3 means +15.3%)
- `num_errors_found` — count of distinct root-cause computational errors in the prior analysis