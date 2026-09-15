
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip jq && rm -rf /var/lib/apt/lists/*

COPY semantics.txt /app/semantics.txt
COPY grammar.txt /app/grammar.txt
COPY imp.lark /app/imp.lark
COPY programs/ /app/programs/
COPY buggy/ /app/buggy/
COPY challenges/ /app/challenges/

RUN pip3 install lark==1.2.2 -q

RUN mkdir -p /app/output

WORKDIR /app
