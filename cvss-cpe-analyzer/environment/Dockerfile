FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN mkdir -p /app/data
COPY data/.hmac_key /app/data/.hmac_key
COPY data/init_db.py /tmp/init_db.py
RUN python3 /tmp/init_db.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    sqlite3 \
    jq \
    xmlstarlet \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/canonical /app/data/feeds /app/output

COPY --from=builder /app/data/nvd_mirror.db /app/data/nvd_mirror.db
COPY data/.hmac_key /app/data/.hmac_key
COPY data/signing_protocol.txt /app/data/signing_protocol.txt
COPY data/scoring_policy.json /app/data/scoring_policy.json
COPY data/canonical/nvd_snapshot.json /app/data/canonical/nvd_snapshot.json
COPY data/inventory.json /app/data/inventory.json
COPY data/feeds/epss_scores.csv /app/data/feeds/epss_scores.csv
COPY data/feeds/kev_catalog.json /app/data/feeds/kev_catalog.json

WORKDIR /app
