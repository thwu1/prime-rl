FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    cmake \
    libboost-dev \
    && rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
RUN pip3 install numpy==1.26.4 -q && \
    python3 /tmp/generate_data.py && \
    rm /tmp/generate_data.py

WORKDIR /app
