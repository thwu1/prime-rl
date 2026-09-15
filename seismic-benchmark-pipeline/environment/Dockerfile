FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3-dev libhdf5-dev && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

COPY generate_data.py /tmp/generate_data.py
COPY seisbench_format.md /app/docs/seisbench_format.md

RUN mkdir -p /app/raw_data /app/output && python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
