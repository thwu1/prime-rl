FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*


COPY CMakeLists.txt /app/CMakeLists.txt
COPY posit16.h /app/posit16.h
COPY posit16.c /app/posit16.c
COPY test_driver.c /app/test_driver.c

WORKDIR /app
