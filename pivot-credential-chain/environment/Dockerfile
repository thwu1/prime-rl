
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    openssl \
    john \
    && rm -rf /var/lib/apt/lists/*

COPY setup_env.py /tmp/setup_env.py
RUN pip3 install pycryptodome==3.21.0 -q \
    && python3 /tmp/setup_env.py \
    && rm -f /tmp/setup_env.py \
    && pip3 uninstall -y pycryptodome 2>/dev/null || true

RUN mkdir -p /app/results
WORKDIR /app
