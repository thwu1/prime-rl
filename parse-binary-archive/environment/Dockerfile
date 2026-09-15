FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3 gcc make && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/parsers /app/data /app/src

COPY parser_alpha.c /app/parsers/parser_alpha.c
COPY parser_beta.c /app/parsers/parser_beta.c
COPY parser_gamma.c /app/parsers/parser_gamma.c
COPY Makefile /app/Makefile
COPY pipeline.py /app/pipeline.py
COPY gen_data.py /tmp/gen_data.py

RUN cd /app && make
RUN python3 /tmp/gen_data.py && rm /tmp/gen_data.py

WORKDIR /app
