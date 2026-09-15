FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip zstd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/taskdata/frames /app/output

COPY setup_data.py /opt/taskdata/setup_data.py
RUN python3 /opt/taskdata/setup_data.py && rm /opt/taskdata/setup_data.py

WORKDIR /app
