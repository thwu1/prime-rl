FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


ENV DEBIAN_FRONTEND=noninteractive

RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    apt-get update && apt-get install -y \
    python3 python3-pip \
    tshark tcpdump socat xxd netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY protocol_spec.md /app/protocol_spec.md
COPY buggy_server.py /app/server.py
COPY generate_traces.py /tmp/generate_traces.py
RUN python3 /tmp/generate_traces.py && rm /tmp/generate_traces.py

WORKDIR /app
