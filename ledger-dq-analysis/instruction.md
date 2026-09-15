A payment platform's double-entry bookkeeping ledger has been flagged by auditors for reconciliation failures. The ledger event data is stored in a PostgreSQL database (database: `ledger`, user: `ledger`, local trust authentication). The PostgreSQL service is installed but not running.

Supporting data:
- `/app/config/fund_flows.json` — fund flow definitions including expected event types, intermediate (clearing) accounts, and terminal accounts per lifecycle
- `/app/config/thresholds.json` — operational parameters
- `/app/data/bank_settlements.csv` — reference transaction IDs expected from upstream banking partners

Produce `/app/output/dq_report.json`:

```json
{
  "summary": {
    "total_events": "<int>",
    "total_transactions": "<int>",
    "overall_dq_score": "<float>"
  },
  "clearing": {
    "<fund_flow_name>": {
      "score": "<float>",
      "total_transactions": "<int>",
      "uncleared_transactions": [
        {"transaction_id": "<id>", "root_cause": "<missing_counterpart|amount_mismatch|property_mismatch|duplicate>"}
      ]
    }
  },
  "timeliness": {
    "threshold_hours": "<int>",
    "total_late": "<int>",
    "late_transactions": ["<transaction_id>"]
  },
  "completeness": {
    "total_expected": "<int>",
    "total_found": "<int>",
    "missing_transactions": ["<transaction_id>"]
  }
}
```

`total_transactions` is the count of distinct transaction IDs present in the ledger. Each component score is the fraction of transactions passing that check. `overall_dq_score` is the arithmetic mean of the aggregate clearing score (across all flows combined), the timeliness score, and the completeness score.