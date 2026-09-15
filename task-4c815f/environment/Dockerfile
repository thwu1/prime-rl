FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y gcc make python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY app/ /app/
WORKDIR /app

# Pre-build the original vulnerable binary with ASAN for test verification
RUN make asan && \
    cp vdriver_asan vdriver_asan_original && \
    cp -r src src_original && \
    make clean
