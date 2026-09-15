Implement a program at `/app/solver.py` that reads an SDF 1.8 scene file describing a robotic workcell and a YAML file specifying spatial constraints between objects, then computes valid 3D placements for all non-anchor objects that satisfy every constraint without any inter-object overlaps.

The input scene `/app/scene.sdf` defines a 17-object workcell with mixed geometry primitives (box, cylinder, sphere), some with non-axis-aligned orientations. The constraint file `/app/constraints.yaml` specifies 22 spatial relations including support, containment, directional ordering, and proximity between objects. The solver must produce four output files: a solved SDF scene, a placements JSON, a stability report for stacked assemblies, and a constraints satisfaction report. It must also support generating multiple distinct placement variants for a given scene and produce identical output for identical seeds.

The solver must reject the unsatisfiable scene at `/app/scene_cyclic.sdf` + `/app/constraints_cyclic.yaml` with a non-zero exit code and a diagnostic error message.

The complete interface specification — covering SDF pose semantics, coordinate conventions, constraint definitions, collision requirements, stability verification criteria, and all input/output formats — is at `/app/api_spec.txt`.

CLI: `python3 /app/solver.py --scene <sdf> --constraints <yaml> --output-dir <dir> --num-placements N --seed S`