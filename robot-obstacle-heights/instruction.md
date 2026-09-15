A robot testing facility stores obstacle course configurations and evaluation queries in a SQLite database at `/data/obstacles.db`. A configuration manifest at `/data/manifest.json` describes the output format, and the detailed problem statement is at `/data/problem.md`.

For each query [l, r] across all test suites, compute the maximum final height achievable by a robot with starting height chosen optimally from [0, d], after traversing obstacles at positions l through r. Write answers to `/app/output.txt` in the format specified by the manifest, then verify with `validate-output /app/output.txt`.

The largest test suite contains 100,000 obstacles and 100,000 queries.