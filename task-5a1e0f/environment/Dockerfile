FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    graphviz \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sL https://github.com/babashka/babashka/releases/download/v1.3.191/babashka-1.3.191-linux-amd64-static.tar.gz \
    | tar xz -C /usr/local/bin \
    && bb --version

RUN mkdir -p /app/histories /app/viz

COPY generate_histories.py /tmp/generate_histories.py
RUN python3 /tmp/generate_histories.py && rm /tmp/generate_histories.py

WORKDIR /app
