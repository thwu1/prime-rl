FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    python3 \
    python3-pip \
    && (apt-get purge -y python3-pytest 2>/dev/null || true) \
    && rm -rf /var/lib/apt/lists/* \
    && (pip3 uninstall -y pytest 2>/dev/null || true)

COPY app/ /app/

WORKDIR /app
