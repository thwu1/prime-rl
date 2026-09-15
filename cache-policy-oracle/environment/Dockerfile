FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/traces /app/simulator /app/policies /app/validation /app/native

COPY config.json /app/config.json
COPY generate_traces.py /app/generate_traces.py
COPY run_eval.py /app/run_eval.py
COPY simulator/ /app/simulator/
COPY policies/ /app/policies/
COPY validation/ /app/validation/
COPY native/ /app/native/

RUN python3 /app/generate_traces.py

WORKDIR /app
