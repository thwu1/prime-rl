FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

COPY model.py /app/model.py
COPY hardware_spec.json /app/hardware_spec.json
COPY profiler.py /app/profiler.py
COPY diagnostic_log.txt /app/diagnostic_log.txt
COPY report_schema.json /app/report_schema.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
