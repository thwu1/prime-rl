FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        make \
        libc6-dev \
        valgrind \
        binutils \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app
COPY regex_engine.h /app/regex_engine.h
COPY regex_engine.c /app/regex_engine.c
COPY test_driver.c /app/test_driver.c
COPY test_vectors.txt /app/test_vectors.txt
COPY Makefile /app/Makefile

WORKDIR /app
