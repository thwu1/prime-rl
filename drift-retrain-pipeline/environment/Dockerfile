FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install mlflow==2.17.2 scikit-learn==1.5.2 pandas==2.2.3 numpy==1.26.4

WORKDIR /app

COPY setup_env.py /tmp/setup_env.py
COPY config.yaml /app/config.yaml

RUN python3 /tmp/setup_env.py && rm /tmp/setup_env.py
