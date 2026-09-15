FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections \
    && apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    tshark \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY setup_db.py /tmp/setup_db.py
COPY pcap_generator.py /tmp/pcap_generator.py
COPY inventory.json /app/inventory.json
COPY env_config.json /app/env_config.json
COPY vuln_assess.py /app/vuln_assess.py
COPY traffic_analyzer.sh /app/traffic_analyzer.sh
COPY incident_report.txt /app/incident_report.txt
COPY ssvc_policy.json /app/ssvc_policy.json
COPY mission_impact.json /app/mission_impact.json

RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py
RUN python3 /tmp/pcap_generator.py && rm /tmp/pcap_generator.py
RUN chmod +x /app/traffic_analyzer.sh

WORKDIR /app
