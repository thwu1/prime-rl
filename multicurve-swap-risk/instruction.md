Market data for EUR interest rate instruments is provided in `/app/market_data.json`. A swap portfolio with trading conventions is specified in `/app/portfolio.json`.

Create `/app/pricer.py` that produces `/app/results.json` containing accurate mark-to-market valuations and risk measures for the entire portfolio.

The market data file contains two distinct sets of rate inputs — OIS rates and Euribor 6M rates — along with their construction conventions. The portfolio file defines the swaps and their trading conventions. QuantLib-Python is installed in the environment.

For each swap, compute its NPV, fair rate, and fair spread. Also compute DV01 — the change in NPV from a +1 basis point parallel shift of all market input rates. Report OIS discount factors at settlement + {1Y, 5Y, 10Y, 30Y}.

Write `/app/results.json`:
```json
{
  "evaluation_date": "YYYY-MM-DD",
  "settlement_date": "YYYY-MM-DD",
  "swaps": [
    {
      "id": "<string>",
      "npv": "<float>",
      "fair_rate": "<float>",
      "fair_spread": "<float>",
      "dv01": "<float: NPV(+1bp) - NPV(base)>"
    }
  ],
  "portfolio_npv": "<float: sum of swap NPVs>",
  "portfolio_dv01": "<float: sum of swap DV01s>",
  "ois_discount_factors": {
    "1Y": "<float>",
    "5Y": "<float>",
    "10Y": "<float>",
    "30Y": "<float>"
  }
}
```