FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip python3-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY generate_model.py /app/generate_model.py
COPY generate_calibration.py /app/generate_calibration.py
COPY config.json /app/config.json
