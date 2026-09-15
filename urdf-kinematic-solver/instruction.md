Three URDF robot arm descriptions are provided at `/app/variant_a.urdf`, `/app/variant_b.urdf`, and `/app/variant_c.urdf`. One or more may contain structural errors that make them invalid. Analysis parameters and query configurations are in `/app/queries.json`.

Produce a comprehensive kinematic and workspace evaluation of these robot arms. Write all results to `/app/output/results.json`, conforming exactly to the JSON Schema at `/app/output_schema.json`. Read that schema carefully — it specifies every required field, its type, and its meaning.

For each variant, determine whether the URDF is structurally valid and report the validation metrics defined in the schema. For each valid variant, also generate a kinematic tree visualization as a PNG at `/app/output/<variant_id>_tree.png`.

For valid variants, perform the kinematic analysis described in `queries.json` for each query configuration, and the workspace analysis using the parameters specified there. Set `kinematic_analysis` and `workspace_analysis` to `null` for any invalid variant.

Finally, populate the `comparative_summary` identifying which valid variant is best for each workspace metric.

Available system packages: `liburdfdom-tools`, `graphviz`. Additional libraries can be installed as needed.