
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    libxml2-utils \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

COPY create_data.py /tmp/create_data.py
RUN python3 /tmp/create_data.py && rm /tmp/create_data.py

COPY evaluator.py /app/evaluator.py

WORKDIR /app
