FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY prepare_data.py /setup/prepare_data.py
COPY metrics.py /app/metrics.py

RUN pip3 install --no-cache-dir pyarrow==17.0.0 -q && \
    mkdir -p /tmp/bright /app/data /app/.bright_eval && \
    curl --fail --retry 5 --retry-delay 3 -sL -o /tmp/bright/docs.parquet \
      "https://huggingface.co/datasets/xlangai/BRIGHT/resolve/main/documents/pony-00000-of-00001.parquet" && \
    curl --fail --retry 5 --retry-delay 3 -sL -o /tmp/bright/examples.parquet \
      "https://huggingface.co/datasets/xlangai/BRIGHT/resolve/main/examples/pony-00000-of-00001.parquet" && \
    curl --fail --retry 5 --retry-delay 3 -sL -o /tmp/bright/reasoning.parquet \
      "https://huggingface.co/datasets/xlangai/BRIGHT/resolve/main/gpt4_reason/pony-00000-of-00001.parquet" && \
    python3 /setup/prepare_data.py && \
    rm -rf /tmp/bright /setup

WORKDIR /app
