FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    python3 \
    python3-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install COCO benchmarking framework (provides cocoex for experiments)
# and numpy (required by COCO and for numerical computation)
RUN pip3 install numpy==1.26.4 coco-experiment==2.8.2

# Set up experiment directory structure
RUN mkdir -p /app/experiment

COPY config.py /app/experiment/config.py
COPY run_benchmark.py /app/experiment/run_benchmark.py
COPY baseline_optimizer.py /app/experiment/baseline_optimizer.py
COPY analyze.py /app/experiment/analyze.py

RUN chmod +x /app/experiment/run_benchmark.py /app/experiment/analyze.py

WORKDIR /app
