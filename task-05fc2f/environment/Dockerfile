FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y build-essential git python3-pip && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/rui314/chibicc.git /app/chibicc && cd /app/chibicc && make

RUN mkdir -p /app/examples
COPY example1.c /app/examples/example1.c
COPY example2.c /app/examples/example2.c
COPY example3.c /app/examples/example3.c

WORKDIR /app
