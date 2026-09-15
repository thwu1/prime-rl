A methodology specification describing nine analytics for a USD fixed-rate callable bond is at `/app/spec.md`. Market data (curve quotes, bond terms, model parameters, stress scenario) is at `/app/market_data.json`.

Create `/app/analyze.py` that implements every analytic defined in the specification, using the provided market data, and writes all results to `/app/results.json` in the exact format the specification requires.

The QuantLib Python package is pre-installed.