FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install Suricata IDS and task dependencies
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    (add-apt-repository -y ppa:oisf/suricata-stable || true) && \
    apt-get update && \
    apt-get install -y suricata python3-pip python3-scapy jq tcpdump && \
    rm -rf /var/lib/apt/lists/*

# Tune Suricata config for container (single-threaded)
COPY tune_config.py /tmp/tune_config.py
RUN python3 /tmp/tune_config.py && rm /tmp/tune_config.py

# Create task directory structure
RUN mkdir -p /app/rules /app/logs

# Generate incident PCAP from synthetic traffic patterns
COPY pcap_gen.py /tmp/pcap_gen.py
RUN python3 /tmp/pcap_gen.py && rm /tmp/pcap_gen.py

# Deploy the buggy detection rules and threshold configuration
COPY deployed_rules.txt /app/rules/deployed.rules
COPY broken_threshold.txt /app/threshold.config

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
