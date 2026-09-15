FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY input/ /app/hl7_input/
COPY mapping_spec.md /app/mapping_spec.md
COPY bulk_export/ /app/bulk_export/
COPY conceptmaps/ /app/conceptmaps/
COPY migration_config.json /app/migration_config.json
COPY report_schema.json /app/report_schema.json

RUN mkdir -p /app/output/bundles /app/staging
