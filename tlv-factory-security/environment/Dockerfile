FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip openssl && \
    rm -rf /var/lib/apt/lists/*

COPY app/schemas/ /app/schemas/
COPY app/policies/ /app/policies/
COPY app/spec.md /app/spec.md

RUN mkdir -p /app/test_keys && \
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:prime256v1 -out /app/test_keys/private.pem && \
    openssl pkey -in /app/test_keys/private.pem -pubout -out /app/test_keys/public.pem

WORKDIR /app
