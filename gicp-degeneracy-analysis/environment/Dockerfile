FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==1.26.4
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    cmake \
    g++ \
    libeigen3-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install small_gicp==1.0.0 numpy==1.26.4
COPY --from=builder /app/scans /app/scans
WORKDIR /app
