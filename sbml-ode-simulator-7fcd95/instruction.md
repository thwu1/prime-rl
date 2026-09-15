Build a command-line SBML Level 3 Version 2 simulator at `/app/sbml_sim.py` that reads an SBML XML model and a settings file, numerically simulates the model, and writes CSV results to stdout.

**Usage:** `python3 /app/sbml_sim.py <model.xml> <settings.txt>`

**Output:** CSV to stdout with a header row matching the variables listed in the settings file, prefixed by `time`. Numeric values at each time step must match reference results within tolerances defined in the settings file using: `|expected - actual| <= (absolute + relative * |expected|)`.

**Settings file format** has fields: `start`, `duration`, `steps`, `variables` (comma-separated), `absolute`, `relative`, `amount` (species reported in amount units), `concentration` (species reported in concentration units). Time points are evenly spaced from `start` to `start + duration` inclusive, totaling `steps + 1` rows.

**Required SBML features the simulator must handle:**

- **Compartments**: including zero-dimensional (spatialDimensions=0). Compartment `size` is used for amount/concentration conversion.
- **Species**: `initialAmount` and `initialConcentration`. When `hasOnlySubstanceUnits="false"` and compartment dimensionality > 0, the species symbol in all math expressions represents concentration (= amount / compartment size). When `hasOnlySubstanceUnits="true"` or compartment is 0D, the symbol represents amount directly. Boundary species (`boundaryCondition="true"`) are not changed by reactions.
- **Parameters**: global parameters with `value` attribute.
- **Reactions with kinetic laws**: kinetic law MathML gives reaction rate in substance/time. Species amounts change by `stoichiometry * rate`, subtracted for reactants and added for products.
- **Function definitions**: MathML `lambda` expressions defining reusable functions invocable in kinetic laws.
- **Initial assignments**: override declared initial values before simulation starts.
- **Assignment rules**: continuously assign a variable's value from a MathML expression.
- **Rate rules**: define `d(variable)/dt` via MathML.
- **Piecewise expressions**: including nested `piecewise` in MathML.
- **Events**: fire when a trigger condition transitions from false to true. All event assignment values are computed from pre-assignment state and applied simultaneously. For species with `hasOnlySubstanceUnits="false"`, event assignments set concentration; new amount = assigned_concentration * compartment_size_at_trigger_time.
- **`csymbol` time**: MathML `csymbol` with `definitionURL` containing "time" evaluates to current simulation time.

**Constraints:** Do not use `libroadrunner`, `libsbml`, `tellurium`, `python-libsbml`, `antimony`, `biosimulators`, or any SBML-domain library. Standard library XML parsing plus general numerical libraries (e.g., scipy, numpy) are permitted.

**Test cases** are at `/app/test_cases/case_a/` through `/app/test_cases/case_e/`, each containing `model.xml` and `settings.txt`. All five must pass tolerance checks. The simulator must also produce correct results on novel SBML models not present in the test cases.
