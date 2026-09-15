FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip xxd sqlite3 build-essential wget && rm -rf /var/lib/apt/lists/*

RUN wget -q https://github.com/usnistgov/trec_eval/archive/refs/tags/v9.0.8.tar.gz -O /tmp/trec_eval.tar.gz && \
    mkdir -p /app/tools && \
    tar xzf /tmp/trec_eval.tar.gz -C /app/tools/ && \
    mv /app/tools/trec_eval-9.0.8 /app/tools/trec_eval && \
    rm /tmp/trec_eval.tar.gz

COPY generate_data.py /setup/generate_data.py
RUN python3 /setup/generate_data.py && rm -rf /setup

COPY docs/ /app/docs/
COPY tools/dump_header.py /app/tools/dump_header.py
COPY tools/verify_alignment.py /app/tools/verify_alignment.py
RUN chmod +x /app/tools/*.py
