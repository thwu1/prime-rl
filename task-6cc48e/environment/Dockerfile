FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip build-essential git && rm -rf /var/lib/apt/lists/*

# Install trec_eval (standard IR evaluation tool)
RUN git clone --depth 1 https://github.com/usnistgov/trec_eval.git /tmp/trec_eval && \
    cd /tmp/trec_eval && make && cp trec_eval /usr/local/bin/trec_eval && \
    rm -rf /tmp/trec_eval

RUN mkdir -p /app/data

# Generate evaluation data with embedded quality issues
COPY gen_data.py /tmp/gen_data.py
RUN python3 /tmp/gen_data.py && rm /tmp/gen_data.py

# Install the evaluation pipeline under audit
COPY pipeline.py /app/pipeline.py

WORKDIR /app
