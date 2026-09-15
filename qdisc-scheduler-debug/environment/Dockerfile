FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    tshark \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY sla_spec.json /app/sla_spec.json
COPY pcap_generator.py /app/pcap_generator.py
COPY run_shaper.py /app/run_shaper.py
COPY tc_template.sh /app/tc_template.sh

RUN python3 /app/pcap_generator.py /app/sla_spec.json /app/capture.pcap

