
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-dev gcc make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/experiment

COPY data/qrels.txt /app/experiment/qrels.txt
COPY data/system_alpha.run /app/experiment/system_alpha.run
COPY data/system_beta.run /app/experiment/system_beta.run
COPY data/system_gamma.run /app/experiment/system_gamma.run
COPY data/README.txt /app/experiment/README.txt
COPY scripts/eval_pipeline.py /app/eval_pipeline.py

RUN cd /app && python3 eval_pipeline.py

WORKDIR /app
