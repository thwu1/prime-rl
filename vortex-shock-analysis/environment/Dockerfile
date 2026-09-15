FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    libgl1 \
    libglu1-mesa \
    libgomp1 \
    libxrender1 \
    libxcursor1 \
    libxft2 \
    libxinerama1 \
    libxext6 \
    libxfixes3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/results

COPY ci2_init.py /app/ci2_init.py
COPY output_format.json /app/output_format.json

WORKDIR /app
