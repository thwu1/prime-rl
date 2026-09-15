FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 git && \
    rm -rf /var/lib/apt/lists/*

COPY token_spec.yaml /app/token_spec.yaml
COPY setup_repo.py /tmp/setup_repo.py

RUN python3 /tmp/setup_repo.py

# --- Runtime stage: setup script is NOT in final image layers ---
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app /app

WORKDIR /app
