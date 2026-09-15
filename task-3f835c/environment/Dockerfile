FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/incident /app/baselines /app/reports

COPY incident/sysstat.lst /app/incident/sysstat.lst
COPY incident/system_event.lst /app/incident/system_event.lst
COPY incident/db_cache_advice.lst /app/incident/db_cache_advice.lst
COPY incident/librarycache.lst /app/incident/librarycache.lst
COPY incident/pgastat.lst /app/incident/pgastat.lst
COPY incident/pga_target_advice.lst /app/incident/pga_target_advice.lst
COPY incident/sqlarea.lst /app/incident/sqlarea.lst
COPY incident/parameter.lst /app/incident/parameter.lst
COPY incident/sgastat.lst /app/incident/sgastat.lst
COPY incident/waitstat.lst /app/incident/waitstat.lst
COPY incident/execution_plans.lst /app/incident/execution_plans.lst
COPY incident/schema_info.txt /app/incident/schema_info.txt
COPY incident/README.txt /app/incident/README.txt

COPY reports/consultant_A.json /app/reports/consultant_A.json
COPY reports/consultant_B.json /app/reports/consultant_B.json
COPY reports/consultant_C.json /app/reports/consultant_C.json

COPY baselines/create_baselines.sql /tmp/create_baselines.sql
RUN sqlite3 /app/baselines/baselines.db < /tmp/create_baselines.sql && rm /tmp/create_baselines.sql

RUN test -f /app/incident/sysstat.lst && test -f /app/baselines/baselines.db && test -f /app/reports/consultant_A.json && echo "Data files verified"

WORKDIR /app
