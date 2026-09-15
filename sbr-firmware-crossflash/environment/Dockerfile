FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder


COPY generate_sbrs.py /tmp/generate_sbrs.py
RUN python3 /tmp/generate_sbrs.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    xxd \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/dumps/ /app/dumps/
COPY --from=builder /app/target_spec.json /app/target_spec.json

RUN mkdir -p /app/output

WORKDIR /app
