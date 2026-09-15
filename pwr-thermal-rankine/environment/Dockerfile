
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY plant_specs.toml /app/plant_specs.toml
COPY generate_prior_analysis.py /tmp/generate_prior_analysis.py

RUN pip3 install iapws==1.5.5 -q && \
    python3 /tmp/generate_prior_analysis.py && \
    pip3 uninstall -y iapws -q && \
    rm /tmp/generate_prior_analysis.py && \
    pip3 cache purge 2>/dev/null || true
