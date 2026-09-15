FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://github.com/prometheus/prometheus/releases/download/v2.53.0/prometheus-2.53.0.linux-amd64.tar.gz \
    -o /tmp/prom.tar.gz && \
    tar xzf /tmp/prom.tar.gz -C /tmp && \
    cp /tmp/prometheus-2.53.0.linux-amd64/promtool /usr/local/bin/promtool && \
    chmod +x /usr/local/bin/promtool && \
    rm -rf /tmp/prom.tar.gz /tmp/prometheus-2.53.0.linux-amd64

RUN mkdir -p /app/scrapes

COPY data/scrapes/ /app/scrapes/
COPY data/scrape_metadata.json /app/scrape_metadata.json
COPY data/slo_config.json /app/slo_config.json

WORKDIR /app
