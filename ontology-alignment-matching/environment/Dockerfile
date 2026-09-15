FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    libxml2-utils \
    && rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
COPY verify_data.py /tmp/verify_data.py
RUN python3 /tmp/generate_data.py && python3 /tmp/verify_data.py && rm /tmp/generate_data.py /tmp/verify_data.py

WORKDIR /app
