FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install SimpleITK==2.3.1 numpy==2.1.3 -q

COPY generate_phantom.py /tmp/generate_phantom.py
RUN mkdir -p /app && python3 /tmp/generate_phantom.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/phantom.mha /app/phantom.mha

WORKDIR /app
