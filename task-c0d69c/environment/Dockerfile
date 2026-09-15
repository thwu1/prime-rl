FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        perl \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/brendangregg/FlameGraph.git /opt/FlameGraph && \
    chmod +x /opt/FlameGraph/*.pl

RUN mkdir -p /app/profiles

COPY metadata.json /app/metadata.json
COPY generate_profiles.py /tmp/generate_profiles.py
RUN python3 /tmp/generate_profiles.py && rm /tmp/generate_profiles.py

WORKDIR /app
