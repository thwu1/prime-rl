CrowdSec is installed with the `crowdsecurity/syslog-logs` parser pre-configured (handles s00-raw syslog parsing) and `crowdsecurity/dateparse-enrich` for timestamp normalization. A log file from a custom API gateway called "Nexus" is at `/app/logs/gateway.log`.

The logs use standard BSD syslog format. Two program names appear:
- `nexus-auth`: authentication events with key-value fields `src_ip`, `user`, `result`, `reason`, `mfa`, `sid`
- `nexus-api`: API access events with key-value fields `src_ip`, `method`, `path`, `status`, `ua` (quoted string), `bytes`, `duration_ms`, `sid`

Three attack patterns are embedded in the logs alongside normal traffic:
1. **Brute force** from `203.0.113.42`: repeated auth failures against the same user
2. **Credential stuffing** from `198.51.100.17`: auth failures across many distinct usernames from a single IP
3. **API scanning** from `192.0.2.99`: high rate of HTTP 4xx responses from path enumeration

Build a complete CrowdSec detection pipeline (s01-parse parser, leaky-bucket scenarios, and acquisition config) that generates alerts for all three attacker IPs when the logs are processed. Normal traffic originates from `10.0.x.x` addresses and must not trigger alerts.

Configuration locations:
- Parsers: `/etc/crowdsec/parsers/s01-parse/`
- Scenarios: `/etc/crowdsec/scenarios/`
- Acquisition: `/etc/crowdsec/acquis.d/`
- CrowdSec config: `/etc/crowdsec/config.yaml`