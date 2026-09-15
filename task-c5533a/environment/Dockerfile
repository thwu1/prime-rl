FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pycryptodome==3.21.0 -q

RUN mkdir -p /app/vectors /app/vendor_responses

COPY vectors/ /app/vectors/
COPY gen_vendor_responses.py /tmp/gen_vendor_responses.py

RUN python3 /tmp/gen_vendor_responses.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/vectors /app/results /app/vendor_responses

COPY vectors/ /app/vectors/
COPY --from=builder /app/vendor_responses/ /app/vendor_responses/

WORKDIR /app
