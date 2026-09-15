FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    build-essential \
    jq \
    xxd \
    valgrind \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/formats /app/inputs /app/runtime /app/generated

COPY runtime/parser.h /app/runtime/parser.h
COPY runtime/runtime.c /app/runtime/runtime.c
COPY Makefile.template /app/Makefile.template
COPY spec.md /app/SPEC.md

COPY formats/container.ddl /app/formats/container.ddl
COPY formats/tagged.ddl /app/formats/tagged.ddl
COPY formats/choice.ddl /app/formats/choice.ddl
COPY formats/chunk_stream.ddl /app/formats/chunk_stream.ddl

COPY create_inputs.py /tmp/create_inputs.py
RUN python3 /tmp/create_inputs.py && rm /tmp/create_inputs.py

WORKDIR /app
