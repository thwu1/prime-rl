FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 openssl jq && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==43.0.3 -q

RUN mkdir -p /app /app/rpki_certs

COPY setup_env.py /tmp/setup_env.py
RUN python3 /tmp/setup_env.py && rm /tmp/setup_env.py

COPY aspa_reference.md /app/aspa_reference.md
COPY output_schema.json /app/output_schema.json

WORKDIR /app
