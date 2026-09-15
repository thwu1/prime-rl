FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN echo 'wireshark-common wireshark-common/install-setuid boolean false' | debconf-set-selections && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        tshark \
        aircrack-ng \
        python3-pip \
        wget \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app && \
    wget -q --timeout=60 --tries=3 -O /app/evidence08.pcap \
        https://forensicscontest.com/contest08/evidence08.pcap

WORKDIR /app
