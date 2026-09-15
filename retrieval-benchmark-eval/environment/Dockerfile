FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip gcc make curl jq && rm -rf /var/lib/apt/lists/*

# Build trec_eval from source (optional reference evaluation tool)
RUN (cd /tmp && \
    curl -fsSL https://github.com/usnistgov/trec_eval/archive/refs/heads/master.tar.gz -o trec_eval.tar.gz && \
    tar xzf trec_eval.tar.gz && \
    cd trec_eval-master && make -j && cp trec_eval /usr/local/bin/) || true; \
    rm -rf /tmp/trec_eval*

# Generate benchmark data (with embedded format issues)
COPY setup_benchmark.py /tmp/setup_benchmark.py
RUN python3 /tmp/setup_benchmark.py && rm /tmp/setup_benchmark.py

# Install evaluation pipeline and config
COPY config.json /app/config.json
COPY broken_evaluate.py /app/evaluate.py

# Generate current (incorrect) report
RUN cd /app && python3 evaluate.py

WORKDIR /app
