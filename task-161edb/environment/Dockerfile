FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install semgrep==1.67.0

COPY setup_incident.py /tmp/setup_incident.py
RUN python3 /tmp/setup_incident.py && rm /tmp/setup_incident.py

WORKDIR /app
