A firmware update package at `/app/firmware.bin` was flagged by automated threat detection after multiple deployed NX-series devices exhibited unauthorized outbound network connections. No documentation for this firmware's proprietary binary format is available.

Conduct a comprehensive security assessment and write your findings to `/app/audit.json`:

```json
{
  "container": {"magic": "<4-byte magic>", "device_id": "<string>", "num_sections": 0, "section_names": ["..."]},
  "backdoor": {"function_name": "<name>", "deobfuscation_method": "<description>", "debug_key": "<decoded key string>", "severity": "<critical|high|medium|low>"},
  "signature_analysis": {"signing_key": "<decoded signing key string>", "signature_valid": true, "key_source": "<where found>", "severity": "<critical|high|medium|low>"},
  "config": {"<key>": "<value_or_number>"},
  "supply_chain_anomalies": [{"type": "<category>", "detail": "<description>"}],
  "incident_summary": {"attack_vector": "<how the compromise was introduced>", "persistence_mechanism": "<how access is maintained>", "overall_risk": "<critical|high|medium|low>", "risk_justification": "<explanation of risk rating>"},
  "yara_rule": "rule ... { ... }"
}
```

The `config` dictionary must contain all key-value pairs extracted from the firmware's configuration data. Use string values for text entries and numeric values for integers. The YARA rule must detect the specific compromise patterns you identify. The `incident_summary` must synthesize all findings into a coherent threat narrative with a justified overall risk rating.