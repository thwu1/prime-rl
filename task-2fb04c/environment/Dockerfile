FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip nasm xxd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /tests /solution /logs/verifier

COPY cpu8088.py /app/cpu8088.py
COPY trace_format.md /app/trace_format.md
COPY test_vectors.json /tmp/test_vectors.json
COPY generate_traces.py /tmp/generate_traces.py

RUN python3 /tmp/generate_traces.py /tmp/test_vectors.json /app/traces.bin && \
    rm /tmp/test_vectors.json /tmp/generate_traces.py

WORKDIR /app
