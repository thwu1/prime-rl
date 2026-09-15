
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY allkeys.txt /app/allkeys.txt
COPY collator.py /app/collator.py
COPY uca_spec.txt /app/uca_spec.txt

RUN mkdir -p /app/test_data

COPY test_data_ni.txt /app/test_data/CollationTest_NON_IGNORABLE_subset.txt
COPY test_data_shifted.txt /app/test_data/CollationTest_SHIFTED_subset.txt
