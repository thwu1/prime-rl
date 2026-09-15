FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Task-specific tools: QEC simulation and decoding
RUN pip3 install stim==1.14.0 pymatching==2.2.1

COPY codes.json /app/codes.json
WORKDIR /app
