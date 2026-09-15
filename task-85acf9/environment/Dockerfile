FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip xxd wabt curl && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /app/reference

COPY types.json /app/types.json
COPY interface.wit /app/interface.wit
COPY cabi_skeleton.py /app/cabi.py
COPY check_conformance.py /app/check_conformance.py

COPY gen_reference.py /tmp/gen_reference.py
RUN python3 /tmp/gen_reference.py && rm /tmp/gen_reference.py

WORKDIR /app
