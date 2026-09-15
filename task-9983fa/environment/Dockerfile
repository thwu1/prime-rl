FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y curl gnupg2 python3-pip lsb-release procps && \
    rm -rf /var/lib/apt/lists/*

# Add CrowdSec repository
RUN curl -s https://install.crowdsec.net | bash

# Create a dummy systemctl so crowdsec postinst does not fail in Docker
RUN printf '#!/bin/sh\nexit 0\n' > /usr/bin/systemctl && chmod +x /usr/bin/systemctl

RUN apt-get update && \
    apt-get install -y crowdsec && \
    rm -rf /var/lib/apt/lists/*

# Remove the dummy systemctl after installation
RUN rm -f /usr/bin/systemctl

# Install the syslog-logs parser (it is a parser, NOT a collection) and dateparse-enrich
RUN mkdir -p /var/lib/crowdsec/data /etc/crowdsec/acquis.d && \
    cscli machines add -a --force && \
    cscli hub update && \
    cscli parsers install crowdsecurity/syslog-logs --force && \
    cscli parsers install crowdsecurity/dateparse-enrich --force

COPY config_override.yaml /etc/crowdsec/config.yaml.local

RUN mkdir -p /app/logs
COPY generate_logs.py /tmp/generate_logs.py
RUN python3 /tmp/generate_logs.py > /app/logs/gateway.log && rm /tmp/generate_logs.py

WORKDIR /app
