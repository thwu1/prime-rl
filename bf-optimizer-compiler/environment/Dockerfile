FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip nasm binutils && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/programs

COPY bfcomp_buggy.py /app/bfcomp.py
COPY hello.bf /app/programs/hello.bf
COPY alphabet.bf /app/programs/alphabet.bf

WORKDIR /app
