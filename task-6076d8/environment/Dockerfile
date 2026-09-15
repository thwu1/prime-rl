
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip jq sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY init_env.py /tmp/init_env.py
RUN python3 /tmp/init_env.py && rm /tmp/init_env.py

COPY trf2json /usr/local/bin/trf2json
RUN chmod +x /usr/local/bin/trf2json

COPY output_schema.json /app/output_schema.json

WORKDIR /app
