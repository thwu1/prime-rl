Three numerical analysis problems are specified through configuration and data files in the environment. Start by examining `/app/challenge.json`, which describes each problem's specification file, associated data files, and required output location.

Each problem demands specialized numerical methods — naive approaches (standard quadrature, direct summation, dense linear algebra) will either fail to achieve the required precision or be computationally infeasible.

Compute each answer to at least 10 significant digits. All values must be computed programmatically, not hard-coded. Write results to the output paths specified in the challenge configuration.