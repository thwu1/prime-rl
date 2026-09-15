FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip xxd && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY gguf_spec.md /app/gguf_spec.md
COPY generate_corrupt_model.py /tmp/generate_corrupt_model.py
RUN python3 /tmp/generate_corrupt_model.py && rm /tmp/generate_corrupt_model.py
