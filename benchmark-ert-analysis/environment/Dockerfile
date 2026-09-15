FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    gcc make \
    libsqlite3-dev sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY raw_data/ /app/raw_data/
COPY converter/ /app/converter/
COPY pipeline/ /app/pipeline/
COPY run_pipeline.sh /app/run_pipeline.sh
COPY properties.json /app/properties.json
COPY schema.json /app/schema.json

RUN chmod +x /app/run_pipeline.sh

WORKDIR /app
