FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
WORKDIR /app

COPY generate_dump.py /tmp/generate_dump.py
RUN python3 /tmp/generate_dump.py && rm /tmp/generate_dump.py
