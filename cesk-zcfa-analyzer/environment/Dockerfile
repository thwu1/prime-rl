FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    guile-3.0 \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY lang.py /app/lang.py

RUN mkdir -p /app/programs /app/reference
COPY programs/ /app/programs/
COPY run_guile.sh /app/reference/run_guile.sh
RUN chmod +x /app/reference/run_guile.sh
