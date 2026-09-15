A distributed 3-shard MVCC key-value store records its complete transaction history in a PostgreSQL database on `localhost` (database: `txstore`, user: `auditor`, no password, local socket connection). The PostgreSQL service is installed but not currently running.

The store is designed to provide strict serializability for all transactions, including cross-shard operations. However, the operations team has received reports of anomalous application behavior suggesting the store has been violating its consistency guarantees.

Audit the complete transaction history across all shards. Find every consistency violation, classify it, and write a structured report to `/app/results.json`:

```json
{
  "anomalies": [
    {
      "type": "<classification>",
      "transactions": ["<tx_id>", ...],
      "description": "<explanation of the violation>"
    }
  ],
  "total_transactions": <int>,
  "cross_shard_transactions": <int>,
  "anomaly_count": <int>
}
```

The `transactions` field must list all transaction IDs involved in each violation. Use standard database concurrency anomaly terminology for the `type` field. The `anomaly_count` must equal the length of the `anomalies` array.