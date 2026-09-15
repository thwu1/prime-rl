FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository -y universe && \
    apt-get update && \
    echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    apt-get install -y python3 python3-pip kcat tshark tcpdump && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install crcmod==1.7

RUN mkdir -p /data /setup
COPY generate_fixtures.py /setup/generate_fixtures.py
RUN python3 /setup/generate_fixtures.py

RUN mkdir -p /app
COPY run_stub.sh /app/run.sh
RUN chmod +x /app/run.sh
