FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    cryptsetup-bin \
    python3 \
    python3-pip \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/images /var/verity

COPY setup_images.py /tmp/setup_images.py
RUN python3 /tmp/setup_images.py && rm /tmp/setup_images.py

WORKDIR /app
