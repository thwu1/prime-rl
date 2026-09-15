FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-numpy \
    python3-scipy \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY transforms.py /app/transforms.py
COPY pipeline.py /app/pipeline.py

RUN mkdir -p /app/configs
COPY pipeline.json /app/configs/pipeline.json
COPY settings.json /app/configs/settings.json
