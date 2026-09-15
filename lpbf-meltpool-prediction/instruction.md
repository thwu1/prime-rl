A configuration file at `/app/config.json` specifies thermophysical properties for nickel alloy 718 (IN718), laser powder bed fusion (LPBF) process parameters, and a multi-track pad scanning pattern modeled after NIST AM-Bench benchmark challenge problems.

Using the Rosenthal analytical thermal model, predict melt pool characteristics for this LPBF configuration and write the results to `/app/results.json` with these keys:

- `single_track_half_width_um`: maximum transverse extent (y-coordinate in micrometers) of the liquidus isotherm at the surface (z=0) for a single track deposited on an ambient-temperature substrate.
- `single_track_depth_um`: maximum depth (z-coordinate in micrometers) of the liquidus isotherm along the track centerline (y=0) for the same single track.
- `single_track_length_um`: trailing extent (micrometers) of the liquidus isotherm behind the heat source along the surface centerline (y=0, z=0) for the same single track.
- `preheat_K`: object mapping track number (string key) to the substrate temperature (K) at each track's starting position, accounting for residual thermal accumulation from all previously completed tracks. The pad uses bidirectional raster scanning with turnaround times specified in the config. Compute for track numbers listed in `queries.preheat_tracks`.
- `depth_with_preheat_um`: object mapping track number (string key) to effective melt pool depth (micrometers) when the substrate temperature at that track's start is elevated by prior-track thermal accumulation. Compute for track numbers listed in `queries.depth_tracks`. For track 1, use the ambient temperature.
- `cooling_rate_at_surface_K_per_s`: magnitude of the solidification cooling rate |dT/dt| evaluated at the solidus temperature on the trailing surface centerline (y=0, z=0), for a single track on an ambient substrate (K/s).
- `pdas_um`: primary dendrite arm spacing estimated from the cooling rate using the solidification power-law parameters provided in the config (micrometers).

Round all floating-point values to 2 decimal places, except `cooling_rate_at_surface_K_per_s` which should be rounded to the nearest integer.