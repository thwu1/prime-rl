FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tshark \
    linuxptp \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/scenario /app/reference /app/configs

COPY setup_scenario.py /app/setup_scenario.py
RUN python3 /app/setup_scenario.py && rm /app/setup_scenario.py

WORKDIR /app
