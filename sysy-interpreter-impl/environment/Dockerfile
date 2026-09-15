
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip llvm clang vim && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/spec /app/tests /app/runtime

COPY sysy_spec.md /app/spec/sysy_spec.md
COPY gen_tests.py /tmp/gen_tests.py
RUN python3 /tmp/gen_tests.py && rm /tmp/gen_tests.py
COPY sylib.c /app/runtime/sylib.c
RUN clang -O0 -emit-llvm -c /app/runtime/sylib.c -o /app/runtime/sylib.bc

WORKDIR /app
