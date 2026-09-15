
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 warp-lang==1.14.0

RUN mkdir -p /app/results

COPY config.json /app/config.json
COPY generate_target.py /tmp/generate_target.py
RUN python3 /tmp/generate_target.py && rm /tmp/generate_target.py

WORKDIR /app
