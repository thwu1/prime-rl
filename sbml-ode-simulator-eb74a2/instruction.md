Build a command-line SBML Level 3 Version 2 deterministic simulator at `/app/sbml_sim.py` that reads an SBML model XML file and a settings file, integrates the model's ODE system, and writes a time-course CSV.

**Usage:** `python3 /app/sbml_sim.py <model.xml> <settings.txt> <output.csv>`

Four test cases are provided at `/app/models/case_NNN/` (NNN = 001..004), each containing `model.xml` and `settings.txt`. The simulator must produce numerically correct output for each case.

**Settings file format** (one key-value per line):
- `start`, `duration`, `steps`: simulation time range and sample count (steps+1 output rows, evenly spaced)
- `variables`: comma-separated list of model identifiers to report
- `absolute`, `relative`: tolerance thresholds
- `amount`, `concentration`: which species variables should be reported in substance-amount vs. concentration units

**SBML features the four cases exercise:**
- Compartments (constant and variable-size)
- Species (`hasOnlySubstanceUnits` true and false; `boundaryCondition`)
- Reactions with MathML kinetic laws (including `<times/>`, `<plus/>`, `<minus/>`, `<divide/>`, `<ci>`, `<cn>`)
- Parameters (constant and variable)
- Rate rules (defining d/dt of species, compartments, parameters)
- Assignment rules (algebraic constraints evaluated each step)
- Events with triggers (`<leq/>`), `initialValue`, `persistent`, and event assignments
- Interaction between amount/concentration semantics and variable compartment sizes

**Output CSV:** header row with `time` followed by the variables list from the settings file. Numeric values as floating-point. Species listed in the `concentration` field must be output as amount/compartment-size; species in `amount` are output directly.

The simulator must handle arbitrary SBML models using the features above — not only the four provided cases. Verification includes running the simulator on dynamically generated model variants with modified initial conditions and parameters.

After running all four cases, write `/app/conformance_report.json` — a JSON object mapping each case name (e.g. `"case_001"`) to `"pass"` or `"fail"` based on whether the simulator completed without errors.

No third-party SBML parsing libraries (e.g. python-libsbml, libsbml) may be used. Parse the XML and MathML directly.
