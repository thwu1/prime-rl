`/app/parts/` contains six CadQuery scripts defining components of a shaft-bearing mechanical assembly. `/app/assembly_spec.json` defines the required geometric features and assembly mating constraints for the system. Each script assigns a CadQuery Workplane result to a variable `r`.

Analyze every part by extracting geometric features from the underlying B-Rep shape and produce `/app/analysis.json`:

- `"features"`: object keyed by part name (filename without `.py`), each containing:
  - `"volume_mm3"`: measured solid volume
  - `"cylindrical_surfaces"`: list of `{"radius_mm": float, "axis": [x,y,z]}` for every cylindrical face in the shape, with axis as a unit vector indicating the cylinder's orientation direction

- `"conformance"`: object keyed by part name, each containing:
  - `"passes"`: boolean — true if all extracted features satisfy the assembly spec (1% tolerance on diameters, 5 degrees on axis alignment)
  - `"issues"`: list of strings describing each spec violation, empty list if conforming
  - `"corrected_code"`: full corrected Python source if non-conforming, empty string otherwise

- `"assembly_mates"`: object keyed by mate ID (matching `"mates"` keys in the spec), each containing:
  - `"feasible"`: boolean — true if the mate constraint is satisfied by the as-built (possibly defective) geometry
  - `"radial_clearance_mm"`: computed radial clearance for shaft-in-bore type mates (positive = clearance, negative = interference), null for non-clearance checks
  - `"details"`: string explaining the analysis result

Write corrected source files for any non-conforming parts to `/app/parts_corrected/`.

CadQuery is pre-installed. No GPU is available.