#!/usr/bin/env python3
"""Create the full CrowdSec detection pipeline for Nexus API Gateway logs.

Creates:
  - s01-parse parser for nexus-auth and nexus-api log lines
  - Three leaky-bucket scenarios (brute-force, credential-stuffing, API scan)
  - Acquisition config for /app/logs/gateway.log
Then restarts CrowdSec with log replay to generate alerts.
"""


import os
import shutil
import subprocess
import time

# ---------------------------------------------------------------------------
# YAML content
# ---------------------------------------------------------------------------

PARSER_YAML = r'''filter: "evt.Parsed.program startsWith 'nexus-'"
onsuccess: next_stage
name: custom/nexus-logs
description: "Parse Nexus API Gateway authentication and API access logs"
nodes:
  - filter: "evt.Parsed.program == 'nexus-auth'"
    grok:
      pattern: "src_ip=%{IP:source_ip} user=%{NOTSPACE:username} result=%{WORD:auth_result} reason=%{NOTSPACE:auth_reason} mfa=%{WORD:mfa_status} sid=%{NOTSPACE:session_id}"
      apply_on: message
    statics:
      - meta: log_type
        value: nexus_auth
      - meta: username
        expression: evt.Parsed.username
    nodes:
      - filter: "evt.Parsed.auth_result == 'failure'"
        statics:
          - meta: sub_type
            value: auth_fail
      - filter: "evt.Parsed.auth_result == 'success'"
        statics:
          - meta: sub_type
            value: auth_success
  - filter: "evt.Parsed.program == 'nexus-api'"
    grok:
      pattern: 'src_ip=%{IP:source_ip} method=%{WORD:verb} path=%{NOTSPACE:request_path} status=%{NUMBER:status_code} ua="%{NOTDQUOTE:user_agent}" bytes=%{NUMBER:response_bytes} duration_ms=%{NUMBER:duration} sid=%{NOTSPACE:session_id}'
      apply_on: message
    statics:
      - meta: log_type
        value: nexus_api
      - meta: http_status
        expression: evt.Parsed.status_code
      - meta: http_path
        expression: evt.Parsed.request_path
      - meta: http_verb
        expression: evt.Parsed.verb
statics:
  - meta: service
    value: nexus
  - meta: source_ip
    expression: evt.Parsed.source_ip
'''

BF_SCENARIO_YAML = r'''type: leaky
name: custom/nexus-auth-bf
description: "Detect brute force authentication attempts against Nexus API Gateway"
filter: "evt.Meta.log_type == 'nexus_auth' && evt.Meta.sub_type == 'auth_fail'"
groupby: evt.Meta.source_ip
capacity: 5
leakspeed: "30s"
blackhole: "2m"
labels:
  remediation: true
  type: brute_force
'''

CS_SCENARIO_YAML = r'''type: leaky
name: custom/nexus-credential-stuffing
description: "Detect credential stuffing - many distinct usernames failing from same IP"
filter: "evt.Meta.log_type == 'nexus_auth' && evt.Meta.sub_type == 'auth_fail'"
groupby: evt.Meta.source_ip
distinct: evt.Meta.username
capacity: 8
leakspeed: "60s"
blackhole: "5m"
labels:
  remediation: true
  type: credential_stuffing
'''

API_SCENARIO_YAML = r'''type: leaky
name: custom/nexus-api-scan
description: "Detect API scanning via high rate of 4xx errors from single IP"
filter: "evt.Meta.log_type == 'nexus_api' && evt.Meta.http_status startsWith '4'"
groupby: evt.Meta.source_ip
capacity: 15
leakspeed: "10s"
blackhole: "5m"
labels:
  remediation: true
  type: api_scan
'''

ACQUISITION_YAML = '''source: file
filenames:
  - /app/logs/gateway.log
labels:
  type: syslog
'''


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(f"  wrote {path}")


def run(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", 30)
    return subprocess.run(cmd, **kw)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("[1/4] Writing parser ...")
write("/etc/crowdsec/parsers/s01-parse/nexus-logs.yaml", PARSER_YAML)

print("[2/4] Writing scenarios ...")
write("/etc/crowdsec/scenarios/nexus-auth-bf.yaml", BF_SCENARIO_YAML)
write("/etc/crowdsec/scenarios/nexus-credential-stuffing.yaml", CS_SCENARIO_YAML)
write("/etc/crowdsec/scenarios/nexus-api-scan.yaml", API_SCENARIO_YAML)

print("[3/4] Writing acquisition config ...")
write("/etc/crowdsec/acquis.d/nexus.yaml", ACQUISITION_YAML)

print("[4/4] Restarting CrowdSec with log replay ...")

# Stop any running instance
run(["pkill", "-9", "crowdsec"])
time.sleep(2)

# Clean database state (keep hub/config)
data_dir = "/var/lib/crowdsec/data/"
if os.path.isdir(data_dir):
    shutil.rmtree(data_dir)
os.makedirs(data_dir, exist_ok=True)
run(["cscli", "machines", "add", "-a", "--force"])

# Prepare log replay: empty the file, keep data aside
log_path = "/app/logs/gateway.log"
log_data = ""
if os.path.isfile(log_path):
    with open(log_path) as f:
        log_data = f.read()
    with open(log_path, "w"):
        pass  # truncate

# Start CrowdSec
subprocess.Popen(
    ["crowdsec"],
    stdout=open("/tmp/crowdsec.log", "w"),
    stderr=subprocess.STDOUT,
)
time.sleep(10)

# Replay logs
if log_data:
    with open(log_path, "a") as f:
        f.write(log_data)
    print(f"  replayed {len(log_data.splitlines())} log lines")

# Wait for processing
time.sleep(25)

# Verify alerts
r = run(["cscli", "alerts", "list", "-o", "json", "--limit", "100"])
try:
    import json
    alerts = json.loads(r.stdout) if r.stdout.strip() else []
    ips = set()
    for a in alerts:
        src = (a.get("source") or {})
        ip = src.get("ip") or src.get("value") or ""
        if ip:
            ips.add(ip)
    print(f"\nAlerts generated for IPs: {sorted(ips)}")
    for target in ["203.0.113.42", "198.51.100.17", "192.0.2.99"]:
        status = "OK" if target in ips else "MISSING"
        print(f"  {target}: {status}")
except Exception as exc:
    print(f"Warning: could not parse alerts: {exc}")
    print(f"  stdout: {r.stdout[:300]}")

print("\nDone.")
