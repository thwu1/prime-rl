FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 && \
    rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
RUN pip3 install pyarrow==17.0.0 -q && \
    python3 /tmp/generate_data.py && \
    pip3 uninstall -y pyarrow && \
    rm /tmp/generate_data.py

WORKDIR /app
