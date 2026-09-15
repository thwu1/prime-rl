FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pyarrow==17.0.0

RUN mkdir -p /app/data /app/results

COPY generate_data.py /setup/generate_data.py
RUN python3 /setup/generate_data.py && rm -rf /setup

WORKDIR /app
