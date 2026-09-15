#!/usr/bin/env python3
"""Create deterministic test files for FAT32 forensic repair task."""
import os
import sys


def create_files(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    docs = os.path.join(output_dir, 'docs')
    logs = os.path.join(output_dir, 'logs')
    os.makedirs(docs, exist_ok=True)
    os.makedirs(logs, exist_ok=True)

    # Root: readme.txt (~4600 bytes, 9 clusters @ 512B)
    with open(os.path.join(output_dir, 'readme.txt'), 'wb') as f:
        line = b"The quick brown fox jumps over the lazy dog.\n"
        for _ in range(100):
            f.write(line)

    # Root: data.bin (8192 bytes = exactly 16 clusters @ 512B)
    with open(os.path.join(output_dir, 'data.bin'), 'wb') as f:
        f.write(bytes(range(256)) * 32)

    # Root: config.ini (~700 bytes, 2 clusters @ 512B)
    config = b"""\
[database]
host = 192.168.1.100
port = 5432
name = production_db
user = admin
max_connections = 100
timeout = 30
ssl_mode = require
pool_size = 20
idle_timeout = 300

[logging]
level = INFO
file = /var/log/app.log
max_size = 10485760
backup_count = 5
format = %(asctime)s - %(name)s - %(levelname)s - %(message)s
console = true
json_output = false

[cache]
backend = redis
host = 192.168.1.101
port = 6379
ttl = 3600
max_memory = 536870912
eviction_policy = allkeys-lru

[api]
base_url = https://api.example.com/v2
timeout = 30
retry_count = 3
rate_limit = 1000
auth_method = bearer

[monitoring]
enabled = true
metrics_port = 9090
health_check_interval = 15
alert_email = ops@example.com
"""
    with open(os.path.join(output_dir, 'config.ini'), 'wb') as f:
        f.write(config)

    # docs/notes.txt (~1900 bytes, 4 clusters @ 512B)
    notes = b"""\
Project Development Notes - Q4 2024
=====================================

Phase 1: Infrastructure Setup (Complete)
- Provisioned 3 application servers (app-01 through app-03)
- Configured HAProxy load balancer with round-robin distribution
- Established site-to-site VPN tunnel to partner datacenter (latency: 12ms)
- Deployed monitoring stack: Prometheus 2.48 + Grafana 10.2
- Set up centralized logging with Elasticsearch 8.11 + Kibana
- Configured automated backups to S3-compatible storage (daily, 30d retention)
- Infrastructure as Code: all resources managed via Terraform 1.6

Phase 2: Data Migration (Complete)
- Source: Oracle 19c (legacy), Target: PostgreSQL 16.1
- Total data volume: 2.3TB across 847 tables
- Migration tool: pgloader with custom transformation rules
- Validation: row counts, checksum verification, referential integrity checks
- Performance: 23 slow queries optimized (avg improvement: 340%)
- Data parity: 99.97% automated, 3 records required manual correction
- Rollback plan tested and verified on staging environment

Phase 3: Application Deployment (In Progress)
- Containerized 14 microservices using Docker (multi-stage builds)
- Container registry: Harbor with vulnerability scanning enabled
- CI/CD: GitLab CI with automated test, build, and deploy stages
- Test coverage: unit (92%), integration (78%), e2e (65%)
- Staging UAT: 2 of 3 sign-off cycles completed
- Security: penetration testing complete, zero critical findings
- Performance: load testing shows 4200 req/s at p99 < 200ms

Outstanding Issues:
1. Memory leak in notification-service (JIRA-4521, P2)
   - Heap grows ~50MB/hour under sustained load
   - Suspected cause: unclosed WebSocket connections in retry logic
2. Intermittent timeout in payment gateway integration (JIRA-4533, P1)
   - Occurs during peak hours (14:00-16:00 UTC)
   - Gateway vendor investigating on their end
3. TLS certificate renewal due December 31 (JIRA-4540, P3)
   - Need to coordinate with DNS team for validation
4. Database connection pool exhaustion under burst traffic (JIRA-4545, P2)
   - Current max: 100 connections, need to evaluate increasing to 200
"""
    with open(os.path.join(docs, 'notes.txt'), 'wb') as f:
        f.write(notes)

    # docs/report.csv (~7KB, 14 clusters @ 512B)
    lines = [b"timestamp,cpu_pct,mem_mb,disk_r,disk_w,net_in,net_out\n"]
    for i in range(100):
        day = (i // 24) + 1
        hour = i % 24
        ts = "2024-01-{:02d}T{:02d}:00:00Z".format(day, hour)
        cpu = (37 + i * 7 + i * i) % 100
        mem = 2048 + (i * 13 + i * i * 3) % 4096
        dio_r = (i * 17 + 100) % 10000
        dio_w = (i * 23 + 200) % 10000
        net_in = (i * 31 + 300) % 100000
        net_out = (i * 37 + 400) % 100000
        lines.append("{},{},{},{},{},{},{}\n".format(
            ts, cpu, mem, dio_r, dio_w, net_in, net_out).encode())
    with open(os.path.join(docs, 'report.csv'), 'wb') as f:
        f.writelines(lines)

    # logs/access.log (~5KB, 10 clusters @ 512B)
    log_lines = []
    for i in range(80):
        hour = i % 24
        minute = (i * 7) % 60
        level = ["INFO", "WARN", "DEBUG", "ERROR"][i % 4]
        component = ["auth", "api", "db", "cache", "queue"][i % 5]
        msgs = [
            "Request processed in {}ms".format(12 + i * 3),
            "Connection pool at {}% capacity".format(40 + i % 60),
            "Cache hit ratio: {:.2f}".format(0.5 + (i % 50) / 100),
            "Query executed: {} rows affected".format(i * 17 % 1000),
            "Health check passed for {}".format(component),
        ]
        msg = msgs[i % 5]
        log_lines.append("2024-01-{:02d} {:02d}:{:02d}:00 [{}] {}: {}\n".format(
            (i // 24) + 1, hour, minute, level, component, msg))
    with open(os.path.join(logs, 'access.log'), 'wb') as f:
        f.write(''.join(log_lines).encode())

    # Print file sizes
    for dirpath, _, filenames in os.walk(output_dir):
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, output_dir)
            size = os.path.getsize(path)
            print("  {}: {} bytes ({} clusters)".format(
                rel, size, -(-size // 512)))


if __name__ == '__main__':
    create_files(sys.argv[1])
