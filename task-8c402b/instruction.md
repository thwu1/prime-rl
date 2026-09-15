A Valkey-compatible server configuration is at `/app/valkey.conf` and a binary RDB persistence dump is at `/app/data/dump.rdb`. The dump contains a multi-database key-value store with strings, hashes, lists, sets, and sorted sets. Some encoding threshold parameters in the configuration are set to values that cause certain keys to use less memory-efficient internal representations than necessary.

Produce a comprehensive audit at `/app/audit.json` that combines binary-level analysis of the RDB dump with live runtime information from a running server instance, and identifies which keys are negatively affected by the suboptimal configuration. Do not use pre-built RDB parsing libraries (e.g., rdbtools, redis-rdb-tools).

## Required schema for `/app/audit.json`:

```json
{
  "rdb_version": "<int>",
  "total_keys": "<int>",
  "databases": {"<db_index>": "<key_count>"},
  "type_counts": {"string": "<n>", "list": "<n>", "set": "<n>", "hash": "<n>", "zset": "<n>"},
  "keys_with_expiry": [{"key": "<name>", "db": "<int>", "expiry_ms": "<int>"}],
  "checksum_valid": "<bool>",
  "key_details": {
    "<key_name>": {
      "db": "<int>",
      "type": "<string|list|set|hash|zset>",
      "size": "<int>",
      "value": "<parsed_value>"
    }
  },
  "encoding_report": {
    "<key_name>": {
      "live_encoding": "<encoding type string>",
      "memory_bytes": "<int>"
    }
  },
  "server_info": {
    "redis_version": "<version string>",
    "used_memory_bytes": "<int>"
  },
  "optimization_findings": [
    {
      "key": "<key_name>",
      "current_encoding": "<encoding>",
      "optimal_encoding": "<encoding>",
      "config_parameter": "<param_name>",
      "current_threshold": "<int>",
      "recommended_threshold": "<int>"
    }
  ]
}
```

Value representations: strings as their string value; hashes as `{"field": "value", ...}`; lists as ordered arrays; sets as lexicographically sorted arrays; sorted sets as `[[member, score], ...]` sorted by score ascending. `size` is 1 for strings, element/field/member count for collections. `keys_with_expiry` sorted by key name. `optimization_findings` sorted by key name.