FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN rm -rf /app
COPY app /app

RUN cd /app && make clean && make && test -f /app/compositor

WORKDIR /app
