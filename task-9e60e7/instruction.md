`/app/data/dimuon.csv` contains 100,000 dimuon events from the CMS detector (CERN LHC, Run2010B). Each row is one collision event producing two muons. Columns (suffixed `1`/`2` per muon): `Run`, `Event`, `Type` (reconstruction quality: `G`=Global, `T`=Tracker), `E`, `px`, `py`, `pz` (four-momentum, GeV), `pt`, `eta`, `phi` (kinematics), `Q` (charge), and `M` (pre-computed dimuon invariant mass, GeV).

Produce `/app/analyze.py` that writes `/app/results.json` — a complete spectroscopic analysis of the dimuon invariant mass spectrum (~2–110 GeV). The output must include: an independent invariant mass cross-check reporting the maximum deviation from the `M` column, event counts before and after physics quality selections, a catalog of every statistically significant resonance peak (PDG-standard name, fitted mass, FWHM width, signal yield, significance in σ), and yield ratios normalizing each identified quarkonium state to the vector boson.

Required schema for `/app/results.json`:

    {
      "validation": {
        "mass_recomputation_max_deviation_gev": <float>,
        "total_events": <int>,
        "selected_events": <int>
      },
      "resonances": [
        {
          "name": "<string>",
          "fitted_mass_gev": <float>,
          "fitted_width_gev": <float>,
          "yield": <int>,
          "significance_sigma": <float>
        }
      ],
      "yield_ratios": {"<name>": <float>}
    }

Run: `python3 /app/analyze.py`