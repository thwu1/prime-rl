FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-yaml \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/backup /app/output /app/schemas

COPY backup_descriptor.json /app/backup/backup_descriptor.json
COPY target_config.yaml /app/target_config.yaml
COPY create_modules_db.sql /tmp/create_modules_db.sql
RUN sqlite3 /app/backup/modules.db < /tmp/create_modules_db.sql && rm /tmp/create_modules_db.sql
COPY backup_descriptor_schema.json /app/schemas/backup_descriptor_schema.json
COPY migration_report_schema.json /app/schemas/migration_report_schema.json

WORKDIR /app
