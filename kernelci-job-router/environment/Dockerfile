FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-yaml jq sqlite3 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY labctl.py /app/labctl
COPY kci-events.py /app/kci-events
COPY kci_router.py /app/kci_router.py
RUN chmod +x /app/labctl /app/kci-events /app/kci_router.py

COPY pipeline_config.yaml /app/pipeline_config.yaml
COPY checkout_events.json /app/checkout_events.json
COPY device_catalog.json /app/device_catalog.json
COPY ROUTING_SPEC.md /app/ROUTING_SPEC.md

COPY create_reliability_db.py /tmp/create_reliability_db.py
RUN python3 /tmp/create_reliability_db.py && rm /tmp/create_reliability_db.py

ENV PATH="/app:${PATH}"
