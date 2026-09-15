FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN pip3 install numpy==2.1.3
COPY generate_data.py /tmp/generate_data.py
COPY sensor_config.yaml /app/sensor_config.yaml
RUN python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/scans /app/scans
COPY --from=builder /app/sensor_config.yaml /app/sensor_config.yaml
WORKDIR /app
