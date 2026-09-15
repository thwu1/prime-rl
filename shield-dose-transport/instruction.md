A crewed spacecraft on a Mars round-trip mission is exposed to galactic cosmic radiation (GCR) and solar particle events (SPE). The vehicle can be fitted with several candidate multilayer shield configurations composed of different structural and protective materials. An assessment of the radiation dose equivalent behind each shield configuration is required to determine whether crew career dose limits are met over the full mission duration.

Nuclear interaction properties for all candidate shield materials, incident radiation spectra for the environments encountered during the mission, dosimetric conversion coefficients, and the candidate shield layer specifications are provided in `/app/data/transport_data.h5` (HDF5 format). The mission timeline, exposure durations, and career dose limit are in `/app/data/mission.json`.

## Required outputs

Write the following JSON files to `/app/results/`:

### `/app/results/config_dose_rates.json`

Ambient dose equivalent rate (microSv/h) for each radiation environment and each shield configuration:

```json
{
  "gcr_1au_avg": {"bare": <float>, "config_A": <float>, "config_B": <float>, "config_C": <float>, "config_D": <float>, "config_E": <float>, "config_F": <float>},
  "gcr_1au_min": {"bare": <float>, "config_A": <float>, ...},
  "gcr_1au_max": {"bare": <float>, "config_A": <float>, ...},
  "gcr_1_5au": {"bare": <float>, "config_A": <float>, ...}
}
```

### `/app/results/mission_doses.json`

Cumulative dose for each shield configuration across all mission legs:

```json
{
  "bare": {
    "leg1_dose_mSv": <float>,
    "spe_dose_mSv": <float>,
    "leg2_dose_mSv": <float>,
    "leg3_dose_mSv": <float>,
    "total_dose_mSv": <float>,
    "within_limit": <bool>
  },
  "config_A": {...},
  "config_B": {...},
  "config_C": {...},
  "config_D": {...},
  "config_E": {...},
  "config_F": {...}
}
```

All numerical values must be accurate to within 3% of reference.