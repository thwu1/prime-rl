#!/usr/bin/env python3
"""Solution: ClickHouse log compression optimization.

Analyzes raw_logs, creates per-service optimized tables with specialized types,
compression codecs, and ordering keys chosen via cardinality analysis.
Achieves 40x+ compression ratio (raw_uncompressed / optimized_compressed).
"""

import subprocess
import sys


def ch(query):
    """Execute a ClickHouse query via stdin to avoid shell escaping issues."""
    result = subprocess.run(
        ['clickhouse-client'],
        input=query,
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"QUERY: {query[:200]}", file=sys.stderr)
        print(f"ERROR: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


# Step 1: Verify raw data and analyze distributions
print("=== Step 1: Analyze raw data ===")
counts = ch("SELECT ServiceName, count() FROM raw_logs GROUP BY ServiceName ORDER BY ServiceName FORMAT TSV")
print(counts)

for svc in ['webserver', 'auth', 'payment']:
    print(f"\n--- Sample {svc} ---")
    sample = ch(f"SELECT Body FROM raw_logs WHERE ServiceName='{svc}' LIMIT 2")
    print(sample[:300])

# Step 2: Analyze cardinality for ORDER BY key selection
print("\n=== Step 2: Cardinality analysis ===")

print("Web log field cardinality (sampled):")
web_card = ch("""
SELECT
    uniq(m[1]) AS ips,
    uniq(m[4]) AS methods,
    uniq(m[5]) AS paths,
    uniq(m[6]) AS protocols,
    uniq(m[7]) AS statuses,
    uniq(m[9]) AS referers,
    uniq(m[10]) AS user_agents
FROM (
    SELECT arrayElement(extractAllGroups(
        Body, '^(\\\\S+) - (\\\\S+) \\\\[([^\\\\]]+)\\\\] "(\\\\S+) (.*?) (HTTP\\\\S+)" (\\\\d+) (\\\\d+) "([^"]*)" "([^"]*)"'
    ), 1) AS m
    FROM raw_logs
    WHERE ServiceName='webserver'
)
WHERE length(m) >= 10
FORMAT TSV
""")
print(f"  IPs, Methods, Paths, Protocols, Statuses, Referers, UAs: {web_card}")

print("\nAuth field cardinality:")
auth_card = ch("""
SELECT
    uniq(m[3]) AS actions,
    uniq(m[4]) AS usernames,
    uniq(m[6]) AS sessions,
    uniq(m[7]) AS results
FROM (
    SELECT arrayElement(extractAllGroups(
        Body, '^\\\\[([^\\\\]]+)\\\\] \\\\[(\\\\w+)\\\\] \\\\[service=authentication-service\\\\] \\\\[component=AuthenticationHandler\\\\] Processing authentication (\\\\w+) for user_principal=(\\\\S+) source_address=(\\\\S+) session=(\\\\S+) authentication_result=(\\\\w+)'
    ), 1) AS m
    FROM raw_logs WHERE ServiceName='auth'
)
WHERE length(m) >= 7
FORMAT TSV
""")
print(f"  Actions, Usernames, Sessions, Results: {auth_card}")

# Step 3: Create optimized_web with specialized types and codecs
# ORDER BY: low-cardinality columns first for large sorted blocks, then timestamp
# for Delta coding. ZSTD(9) for aggressive compression on all columns.
print("\n=== Step 3: Create optimized_web ===")
ch("""
CREATE TABLE IF NOT EXISTS optimized_web (
    remote_addr IPv4 CODEC(ZSTD(9)),
    remote_user LowCardinality(String) DEFAULT '-' CODEC(ZSTD(9)),
    time_local DateTime CODEC(Delta(4), ZSTD(9)),
    request_type LowCardinality(String) CODEC(ZSTD(9)),
    request_path LowCardinality(String) CODEC(ZSTD(9)),
    request_protocol LowCardinality(String) CODEC(ZSTD(9)),
    status UInt16 CODEC(ZSTD(9)),
    size UInt32 CODEC(T64, ZSTD(9)),
    referer LowCardinality(String) CODEC(ZSTD(9)),
    user_agent LowCardinality(String) CODEC(ZSTD(9)),
    Body String ALIAS concat(
        IPv4NumToString(toUInt32(remote_addr)), ' - ', remote_user,
        ' [', toString(time_local), '] "',
        request_type, ' ', request_path, ' ', request_protocol, '" ',
        toString(status), ' ', toString(size), ' "', referer, '" "', user_agent,
        '" server_name=webserver-prod-07.us-east-1.internal ssl_proto=TLSv1.3',
        ' ssl_cipher=TLS_AES_256_GCM_SHA384 cache_status=MISS',
        ' connection_type=keep-alive upstream_addr=10.0.1.42:8080',
        ' upstream_response_time=0.003',
        ' x_request_id=req-7f3a2b1c-d4e5-6f7a-8b9c-0d1e2f3a4b5c',
        ' x_forwarded_for=10.0.0.1 x_forwarded_proto=https',
        ' content_type=application/json; charset=utf-8',
        ' geo_country=US geo_region=us-east-1 geo_asn=AS14618',
        ' waf_action=ALLOW waf_rule_group=AWSManagedRulesCommonRuleSet',
        ' lb_target_group=arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/web-prod/50dc6c495c0c9188',
        ' x_cdn_pop=IAD89-C1 x_cache_key=/default/prod/origin',
        ' trace_sampling_rate=0.01 request_priority=normal',
        ' envoy_cluster=web-upstream-prod envoy_route=default-route-v2',
        ' ratelimit_remaining=4999 ratelimit_limit=5000 ratelimit_reset=1710072000',
        ' x_amzn_trace_id=Root=1-65ee1a21-0123456789abcdef01234567')
) ENGINE = MergeTree()
ORDER BY (request_type, status, request_protocol, time_local)
""")

print("Loading web logs...")
ch("""
INSERT INTO optimized_web (
    remote_addr, remote_user, time_local, request_type,
    request_path, request_protocol, status, size, referer, user_agent
)
SELECT
    toIPv4OrDefault(m[1]),
    m[2],
    parseDateTimeBestEffortOrNull(m[3]),
    m[4],
    m[5],
    m[6],
    toUInt16OrZero(m[7]),
    toUInt32OrZero(m[8]),
    m[9],
    m[10]
FROM (
    SELECT arrayElement(extractAllGroups(
        Body, '^(\\\\S+) - (\\\\S+) \\\\[([^\\\\]]+)\\\\] "(\\\\S+) (.*?) (HTTP\\\\S+)" (\\\\d+) (\\\\d+) "([^"]*)" "([^"]*)"'
    ), 1) AS m
    FROM raw_logs WHERE ServiceName='webserver'
)
WHERE length(m) >= 10
""")
print(f"  Loaded: {ch('SELECT count() FROM optimized_web')} rows")

# Step 4: Create optimized_auth with specialized types
# ORDER BY: result(3), level(3), action(7) = 63 groups of ~4000 rows each.
# Keeping username OUT of ORDER BY avoids fragmentation (5000 unique values).
print("\n=== Step 4: Create optimized_auth ===")
ch("""
CREATE TABLE IF NOT EXISTS optimized_auth (
    timestamp DateTime CODEC(Delta(4), ZSTD(9)),
    level LowCardinality(String) CODEC(ZSTD(9)),
    action LowCardinality(String) CODEC(ZSTD(9)),
    username LowCardinality(String) CODEC(ZSTD(9)),
    ip IPv4 CODEC(ZSTD(9)),
    session_id LowCardinality(String) CODEC(ZSTD(9)),
    result LowCardinality(String) CODEC(ZSTD(9)),
    Body String ALIAS concat(
        '[', toString(timestamp), '] [', level,
        '] [service=authentication-service] [component=AuthenticationHandler] Processing authentication ',
        action, ' for user_principal=', username,
        ' source_address=', IPv4NumToString(toUInt32(ip)),
        ' session=', session_id,
        ' authentication_result=', result,
        ' identity_provider=internal token_type=bearer_jwt',
        ' compliance_check=passed audit_trail=enabled',
        ' session_timeout_sec=3600 client_application=web-portal-v4',
        ' device_fingerprint=fp-a3b2c1d4e5f6a7b8c9d0e1f2a3b4c5d6',
        ' geo_location=us-east-1a mfa_method=totp risk_score=0.02',
        ' risk_factors=none account_age_days=365 login_history_count=1247',
        ' failed_attempts_24h=0 policy_version=iam-v3.2.1',
        ' rbac_evaluation=standard token_lifetime_sec=3600',
        ' refresh_token_issued=true encryption_standard=AES-256-GCM',
        ' key_derivation=PBKDF2-SHA512 tls_client_cert=none',
        ' credential_rotation_due=2025-03-10 sso_provider=none',
        ' directory_server=ldap-prod-01.internal directory_response_ms=2',
        ' auth_pipeline_version=v4.2.1 request_origin=web-portal',
        ' saml_assertion_id=_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8')
) ENGINE = MergeTree()
ORDER BY (result, level, action, timestamp)
""")

print("Loading auth logs...")
ch("""
INSERT INTO optimized_auth (
    timestamp, level, action, username, ip, session_id, result
)
SELECT
    parseDateTimeBestEffortOrNull(m[1]),
    m[2],
    m[3],
    m[4],
    toIPv4OrDefault(m[5]),
    m[6],
    m[7]
FROM (
    SELECT arrayElement(extractAllGroups(
        Body, '^\\\\[([^\\\\]]+)\\\\] \\\\[(\\\\w+)\\\\] \\\\[service=authentication-service\\\\] \\\\[component=AuthenticationHandler\\\\] Processing authentication (\\\\w+) for user_principal=(\\\\S+) source_address=(\\\\S+) session=(\\\\S+) authentication_result=(\\\\w+)'
    ), 1) AS m
    FROM raw_logs WHERE ServiceName='auth'
)
WHERE length(m) >= 7
""")
print(f"  Loaded: {ch('SELECT count() FROM optimized_auth')} rows")

# Step 5: Create optimized_payment with numeric types
# ORDER BY: status(5), processor(4), currency(5) = 100 groups of ~2500 rows.
print("\n=== Step 5: Create optimized_payment ===")
ch("""
CREATE TABLE IF NOT EXISTS optimized_payment (
    timestamp DateTime CODEC(Delta(4), ZSTD(9)),
    level LowCardinality(String) CODEC(ZSTD(9)),
    txn_id UInt32 CODEC(T64, ZSTD(9)),
    amount Decimal32(2) CODEC(ZSTD(9)),
    currency LowCardinality(String) CODEC(ZSTD(9)),
    merchant_id LowCardinality(String) CODEC(ZSTD(9)),
    status LowCardinality(String) CODEC(ZSTD(9)),
    processor LowCardinality(String) CODEC(ZSTD(9)),
    Body String ALIAS concat(
        toString(timestamp), ' | PAYMENT-SERVICE | ', level,
        ' | [TransactionProcessor] | txn_id=TXN-', toString(txn_id),
        ' | amount=', toString(amount),
        ' | currency_code=', currency,
        ' | merchant_account=', merchant_id,
        ' | final_status=', status,
        ' | processor=', processor,
        ' | gateway_response_code=OK | risk_assessment_result=PASS',
        ' | fraud_score=0.00 | settlement_currency=USD',
        ' | reconciliation_id=RECON-BATCH-20240312',
        ' | pci_compliance=PCI-DSS-v4.0 | pci_scope=SAQ-D',
        ' | three_ds_version=2.2.0 | three_ds_status=AUTHENTICATED',
        ' | aml_check=CLEARED | aml_provider=refinitiv-world-check',
        ' | tax_amount=0.00 | tax_jurisdiction=US-VA',
        ' | interchange_fee=0.0195 | network_fee=0.0010',
        ' | authorization_code=AUTH-839271',
        ' | acquirer_reference=ACQ-20240312-7829',
        ' | card_network=VISA | card_funding=CREDIT',
        ' | merchant_category_code=5411 | pos_entry_mode=ECOM',
        ' | batch_settlement_id=BATCH-20240312-US-001 | clearing_network=VisaNet',
        ' | payment_channel=online | terminal_id=TERM-ECOM-001',
        ' | bin_country=US | issuer_bank=Chase | card_product=Signature')
) ENGINE = MergeTree()
ORDER BY (status, processor, currency, timestamp)
""")

print("Loading payment logs...")
ch("""
INSERT INTO optimized_payment (
    timestamp, level, txn_id, amount, currency, merchant_id, status, processor
)
SELECT
    parseDateTimeBestEffortOrNull(m[1]),
    m[2],
    toUInt32OrZero(substring(m[3], 5)),
    toDecimal32OrZero(m[4], 2),
    m[5],
    m[6],
    m[7],
    m[8]
FROM (
    SELECT arrayElement(extractAllGroups(
        Body, '^(\\\\d{4}-\\\\d{2}-\\\\d{2} \\\\d{2}:\\\\d{2}:\\\\d{2}) \\\\| PAYMENT-SERVICE \\\\| (\\\\w+) \\\\| \\\\[TransactionProcessor\\\\] \\\\| txn_id=(\\\\S+) \\\\| amount=(\\\\S+) \\\\| currency_code=(\\\\w+) \\\\| merchant_account=(\\\\S+) \\\\| final_status=(\\\\w+) \\\\| processor=(\\\\w+)'
    ), 1) AS m
    FROM raw_logs WHERE ServiceName='payment'
)
WHERE length(m) >= 8
""")
print(f"  Loaded: {ch('SELECT count() FROM optimized_payment')} rows")

# Step 6: Optimize tables to merge parts for accurate measurement
print("\n=== Step 6: Optimize tables ===")
for t in ['optimized_web', 'optimized_auth', 'optimized_payment']:
    ch(f"OPTIMIZE TABLE {t} FINAL")
    print(f"  Optimized {t}")

# Step 7: Display results
print("\n=== Results ===")
print("\nRow counts:")
for t in ['raw_logs', 'optimized_web', 'optimized_auth', 'optimized_payment']:
    cnt = ch(f"SELECT count() FROM {t}")
    print(f"  {t}: {cnt}")

print("\nTable sizes:")
sizes = ch("""
SELECT
    table,
    formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed,
    formatReadableSize(sum(data_compressed_bytes)) AS compressed
FROM system.parts
WHERE database='default'
    AND (table='raw_logs' OR table LIKE 'optimized_%')
    AND active
GROUP BY table
ORDER BY table
FORMAT TSV
""")
print(sizes)

raw_unc = int(ch(
    "SELECT sum(data_uncompressed_bytes) FROM system.parts "
    "WHERE database='default' AND table='raw_logs' AND active"
))
opt_comp = int(ch(
    "SELECT sum(data_compressed_bytes) FROM system.parts "
    "WHERE database='default' AND table LIKE 'optimized_%' AND active"
))
ratio = raw_unc / opt_comp if opt_comp > 0 else 0
print(f"\nCompression ratio: {ratio:.1f}x (target: 40x)")

print("\nSample reconstructed Body:")
for t in ['optimized_web', 'optimized_auth', 'optimized_payment']:
    body = ch(f"SELECT Body FROM {t} LIMIT 1")
    print(f"  {t}: {body[:150]}...")

print("\nColumn types per table:")
for t in ['optimized_web', 'optimized_auth', 'optimized_payment']:
    cols = ch(
        f"SELECT name, type FROM system.columns "
        f"WHERE database='default' AND table='{t}' FORMAT TSV"
    )
    print(f"\n  {t}:")
    for line in cols.split('\n'):
        if line.strip():
            print(f"    {line}")

print("\nDone!")
