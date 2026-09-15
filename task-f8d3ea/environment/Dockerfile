FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3-pip \
    xxd \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY mseed3pack.c sinedata.h mseedformat.h Makefile /app/
