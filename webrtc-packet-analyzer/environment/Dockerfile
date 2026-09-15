FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections \
    && DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tshark \
    openssl \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/captures

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py \
    && test -f /app/captures/tap_alpha.pcap \
    && test -f /app/captures/tap_beta.pcap \
    && test -f /app/session_config.json \
    && test -f /app/session_integrity.hmac \
    && test -f /app/hmac_key.txt \
    && rm /tmp/generate_data.py

WORKDIR /app
