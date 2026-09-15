FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip curl jq && \
    rm -rf /var/lib/apt/lists/*

# Install Prometheus v2.53.0 (provides prometheus and promtool binaries)
RUN curl -sfL https://github.com/prometheus/prometheus/releases/download/v2.53.0/prometheus-2.53.0.linux-amd64.tar.gz -o /tmp/prometheus.tar.gz && \
    tar xzf /tmp/prometheus.tar.gz -C /opt && \
    rm /tmp/prometheus.tar.gz && \
    ln -s /opt/prometheus-2.53.0.linux-amd64/prometheus /usr/local/bin/prometheus && \
    ln -s /opt/prometheus-2.53.0.linux-amd64/promtool /usr/local/bin/promtool

# Generate synthetic metric snapshots and SLO config
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

# Place broken Prometheus configuration and create rules directory
COPY prometheus_broken.yml /app/prometheus/prometheus.yml
RUN mkdir -p /app/prometheus/rules

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
