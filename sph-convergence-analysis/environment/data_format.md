# SPHinXsys XML Regression Data Format

## XML Structure

Each file contains time-series snapshot values stored as attributes on particle elements:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<result>
    <Snapshot_Element>
        <Snapshot number_of_snapshot_for_local_result_="N" />
    </Snapshot_Element>
    <Result_Element>
        <Particle_0 snapshot_0="value" snapshot_1="value" ... snapshot_{N-1}="value" />
    </Result_Element>
</result>
```

## Directory Layout

```
/app/data/
├── config.json
├── fine/                      # finest spatial resolution
│   ├── Pressure/
│   │   ├── reference.xml
│   │   ├── run_0.xml ... run_N.xml
│   └── TotalMechanicalEnergy/
│       └── ...
├── medium/
│   └── ...
└── coarse/                    # coarsest spatial resolution
    └── ...
```

Each resolution directory contains subdirectories per observed quantity. Each quantity directory has a `reference.xml` baseline and numbered `run_*.xml` ensemble members.

## Configuration (config.json)

- `resolutions`: mapping of resolution names to grid spacing (`h`) values
- `quantities`: list of observed quantity names
- `n_snapshots`, `times`: snapshot count and corresponding time values
- `band_fraction`: locality constraint parameter for time-series distance computation
- `distance_threshold`: maximum acceptable distance for run-to-reference comparisons
- `convergence_threshold_mean`: relative mean deviation threshold for ensemble convergence
- `convergence_threshold_variance`: relative variance threshold for ensemble convergence
- `outlier_score_threshold`: threshold for classifying runs as outliers
- `refinement_ratio`: grid spacing ratio between consecutive resolutions
