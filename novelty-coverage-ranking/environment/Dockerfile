
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        sqlite3 \
        jq \
        xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/docs /app/validation /app/output

COPY gen_data.py /tmp/gen_data.py
COPY methodology.md /app/docs/methodology.md
COPY data_format.md /app/docs/data_format.md
COPY output_schema.md /app/docs/output_schema.md
COPY validation_data.json /app/validation/expected_bloaty.json

RUN python3 /tmp/gen_data.py && rm /tmp/gen_data.py
