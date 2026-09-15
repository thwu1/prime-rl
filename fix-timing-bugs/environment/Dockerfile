FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3 \
    python3-pip \
    strace \
    gdb \
    && rm -rf /var/lib/apt/lists/*


COPY recorder.c replayer.c Makefile /app/

RUN cd /app && make all

WORKDIR /app
