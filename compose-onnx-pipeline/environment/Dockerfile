FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install onnx==1.16.2 numpy==1.26.4

COPY generate_models.py /tmp/generate_models.py
RUN python3 /tmp/generate_models.py && rm /tmp/generate_models.py

WORKDIR /app
