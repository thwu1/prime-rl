FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip tshark && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY generate_session.py /tmp/generate_session.py
RUN python3 /tmp/generate_session.py && rm /tmp/generate_session.py

WORKDIR /app
