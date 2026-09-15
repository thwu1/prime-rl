FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    sudo \
    passwd \
    adduser \
    login \
    && rm -rf /var/lib/apt/lists/*

COPY break_system.py /opt/.svc_init.py
COPY bashrc_additions.sh /tmp/bashrc_additions.sh
RUN cat /tmp/bashrc_additions.sh >> /etc/bash.bashrc && rm /tmp/bashrc_additions.sh

RUN mkdir -p /app
WORKDIR /app
