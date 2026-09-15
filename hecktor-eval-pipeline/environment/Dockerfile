
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

COPY setup_data.py /tmp/setup_data.py
COPY spec.md /app/protocol/evaluation_spec.md
RUN pip3 install numpy==2.1.3 nibabel==5.3.2 scipy==1.14.1 -q && \
    python3 /tmp/setup_data.py && \
    rm -f /tmp/setup_data.py && \
    rm -rf /root/.cache/pip
