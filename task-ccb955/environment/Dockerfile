FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && \
    apt-get install -y python3 python3-pip tshark && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY alg_simulator.py /app/alg_simulator.py
COPY tcp_engine.py /app/tcp_engine.py
COPY config.json /app/config.json
COPY validate.py /app/validate.py
COPY generate_pcaps.py /tmp/generate_pcaps.py

RUN python3 /tmp/generate_pcaps.py && rm /tmp/generate_pcaps.py
