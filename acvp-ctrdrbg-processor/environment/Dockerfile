
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip jq && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pycryptodome==3.21.0

RUN mkdir -p /app/prompts /app/responses /app/drbg /app/schema

COPY ctrdrbg_prompt.json /app/prompts/ctrdrbg_prompt.json
COPY response_schema.json /app/schema/response_schema.json
COPY acvp_processor.py /app/acvp_processor.py
COPY drbg_init.py /app/drbg/__init__.py
COPY primitives.py /app/drbg/primitives.py
COPY derivation.py /app/drbg/derivation.py
COPY update.py /app/drbg/update.py
COPY core.py /app/drbg/core.py

WORKDIR /app
