FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip jq sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/structures /app/pae /app/pae_normalized

COPY setup.py /tmp/setup.py
RUN python3 /tmp/setup.py && rm /tmp/setup.py

COPY metrics_skeleton.py /app/metrics.py
COPY run_pipeline_skeleton.sh /app/run_pipeline.sh
COPY pipeline_skeleton.sql /app/pipeline.sql

RUN chmod +x /app/run_pipeline.sh

WORKDIR /app
