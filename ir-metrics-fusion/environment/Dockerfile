FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/usnistgov/trec_eval.git /tmp/trec_eval && \
    cd /tmp/trec_eval && \
    make && \
    cp trec_eval /usr/local/bin/ && \
    rm -rf /tmp/trec_eval

COPY data/ /app/data/
COPY eval/ /app/eval/
COPY schema.json /app/schema.json

WORKDIR /app
