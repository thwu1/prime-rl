
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install torch==2.4.0 --index-url https://download.pytorch.org/whl/cpu

RUN mkdir -p /app

COPY gen_data.py /tmp/gen_data.py
RUN python3 /tmp/gen_data.py && rm /tmp/gen_data.py

COPY rotation_lib.py /app/rotation_lib.py
COPY rotation_analysis.py /app/rotation_analysis.py
COPY analysis_config.toml /app/analysis_config.toml

WORKDIR /app
