FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip bzip2 build-essential sqlite3 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app/eval /app/data /app/runs /app/output /app/trec_eval_src
COPY trec_eval_src/ /app/trec_eval_src/
COPY generate_data.py /tmp/generate_data.py
COPY msmarco_eval_buggy.py /app/eval/msmarco_eval.py
COPY config.json /app/config.json
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py
WORKDIR /app
