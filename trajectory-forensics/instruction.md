Build a forensic analysis tool at `/app/physinfer/analyze.py` that examines 2D rigid-body physics trajectory recordings and assesses their physical plausibility.

## Environment

- `/app/data/` — 8 HDF5 trajectory files containing noisy sensor recordings of rigid bodies in motion, with declared physical parameters embedded in file metadata
- `/app/schema.json` — JSON schema defining the required output format
- `/app/config.toml` — detection thresholds and classification priority rules

## Tool interface

```
python3 /app/physinfer/analyze.py /app/data/<scenario>.h5
```

The tool takes a single HDF5 file path and prints one JSON object to stdout conforming to `/app/schema.json`.

## Objective

For each of the 8 trajectory files, the tool must produce a forensic report that:

- Determines whether the recorded motion is consistent with Newtonian mechanics under the declared parameters, or contains physically implausible behavior
- Infers the actual physical parameters governing the observed dynamics (where determinable from the data)
- Identifies and classifies any discrepancies between declared and observed physics, or violations of fundamental conservation laws at interaction events
- Assigns a quantitative plausibility score reflecting the degree of physical consistency

Explore the HDF5 file structure, the output schema, and the configuration to understand the full scope of what the tool must handle. The data spans single-body and multi-body scenarios involving gravity, surface friction, and elastic interactions in one and two dimensions.