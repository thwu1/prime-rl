A colleague's automated pipeline attempted to characterize Near-Earth Object encounters with Earth during 2024 using JPL ephemeris data. The pipeline output is at `/app/preliminary_analysis.json`.

Internal consistency checks on this output are failing badly: vis-viva residuals are an order of magnitude larger than physically plausible, gravitational deflection angles are near-zero for objects that supposedly passed very close to Earth, and the reported distances don't match what's expected for genuine close approaches. Something is systematically wrong with the computed quantities, but it's unclear whether the issue is in the data retrieval, the reference frame selection, the physics calculations, or some combination.

Produce a corrected analysis at `/app/results.json` containing the encounter dynamics for the 5 closest distinct NEO approaches to Earth in calendar year 2024, with each encounter cross-validated against JPL's published close approach parameters. The file must use this exact schema (all numeric fields must be numeric types, not strings):

```json
{
  "neo_encounters": [
    {
      "designation": "<NEO designation string from close approach data>",
      "close_approach_jd": 0.0,
      "cad_dist_au": 0.0,
      "computed_dist_au": 0.0,
      "cad_v_rel_kms": 0.0,
      "computed_v_rel_kms": 0.0,
      "cad_v_inf_kms": 0.0,
      "computed_v_inf_kms": 0.0,
      "vis_viva_residual": 0.0,
      "tisserand_jupiter": 0.0,
      "deflection_angle_deg": 0.0
    }
  ]
}
```

The `neo_encounters` array must contain exactly 5 entries.

## Validation criteria

- Computed geocentric distance and relative velocity must each agree with the published close approach values within 10%
- Hyperbolic excess velocity must satisfy the two-body encounter energy equation to within 5%, and must agree with published values within 15%
- The vis-viva residual must be below 0.01 (i.e., under 1%)
- The Tisserand parameter must fall within the physically valid range for NEOs: strictly between 1 and 12
- The deflection angle must lie strictly between 0 and 180 degrees, and must be internally consistent with the hyperbolic encounter geometry to within 5%