# Stage 1: Generate synthetic data (discarded from final image —
# generate_data.py never appears in any final layer)
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

# Stage 2: Final task environment
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY --from=builder /app/data/ /app/data/
COPY spec.md /app/data/spec.md

WORKDIR /app
