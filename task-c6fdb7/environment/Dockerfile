FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

WORKDIR /app

RUN mkdir -p /app/data/systems

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

COPY evaluate.py /app/evaluate.py
COPY fusion.py /app/fusion.py
COPY config.yaml /app/config.yaml
COPY readme.md /app/README.md
COPY schema.json /app/schema.json
