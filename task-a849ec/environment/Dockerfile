
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip python3-numpy && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results /app/slam_eval

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY spec.md /app/spec.md

RUN touch /app/slam_eval/__init__.py

WORKDIR /app
