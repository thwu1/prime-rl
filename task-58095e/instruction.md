A seismic source model is provided at `/app/model/` in nshmp-haz directory format. It contains heterogeneous source types (faults defined in XML, faults with projected coordinates in CSV, and gridded point sources in CSV), a ground motion model logic tree with multiple models, and a calculation configuration specifying site parameters, intensity measure levels, and deaggregation settings.

Reference documentation describing the model format, data fields, and calculation methodology is in `/app/docs/`.

Build a pipeline executable as `python3 /app/psha_pipeline.py` that reads the source model and configuration, performs the hazard analysis as described in the documentation, and produces:

- `/app/output/hazard_curves.csv` — columns: `imt,iml,annual_rate,poisson_prob_50yr` (rows grouped by IMT in order PGA, SA0P2, SA1P0; annual rates must decrease monotonically with increasing IML within each IMT)
- `/app/output/uhs.json` — uniform hazard spectrum at the configured return period: `{"return_period": N, "spectral_ordinates": [{"period": T, "sa": V}, ...]}` with one entry per IMT (period 0.0 for PGA), sorted by ascending period
- `/app/output/deagg_pga.json` — PGA deaggregation at the configured return period: `{"target_iml", "return_period", "mean_mag", "mean_dist", "mean_eps", "mode_mag", "mode_dist", "mode_eps"}`