
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
COPY generate_evidence.py /build/generate_evidence.py
RUN python3 /build/generate_evidence.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        jq \
        yara \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/evidence /app/evidence

WORKDIR /app
