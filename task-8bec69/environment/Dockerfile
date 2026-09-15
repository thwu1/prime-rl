FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip jq curl && rm -rf /var/lib/apt/lists/*

# Install promtool from Prometheus v2.53.0 release
RUN curl -sL https://github.com/prometheus/prometheus/releases/download/v2.53.0/prometheus-2.53.0.linux-amd64.tar.gz | tar xz -C /tmp && \
    mv /tmp/prometheus-2.53.0.linux-amd64/promtool /usr/local/bin/promtool && \
    chmod +x /usr/local/bin/promtool && \
    rm -rf /tmp/prometheus-*

COPY metrics/ /app/metrics/
COPY slo_config.json /app/slo_config.json
COPY prom_to_json.py /app/prom_to_json.py
COPY compute_intervals.sh /app/compute_intervals.sh
COPY stub_analyze.py /app/analyze.py
COPY pipeline.sh /app/pipeline.sh
COPY rules/ /app/rules/

RUN chmod +x /app/compute_intervals.sh /app/pipeline.sh

WORKDIR /app
