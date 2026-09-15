FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip flex gcc make binutils && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/examples

COPY spec.md /app/spec.md
COPY Makefile /app/Makefile
COPY example1.mp /app/examples/example1.mp
COPY example2.mp /app/examples/example2.mp
COPY example3.mp /app/examples/example3.mp
