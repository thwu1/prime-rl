FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make gdb sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/lib /app/data /app/output

COPY implicit_weights.c /app/src/implicit_weights.c
COPY implicit_weights.h /app/src/implicit_weights.h
COPY Makefile /app/Makefile
COPY collator.py /app/collator.py
COPY register_collation.py /app/register_collation.py
COPY run_conformance.py /app/run_conformance.py
COPY multilingual_dataset.txt /app/data/multilingual_dataset.txt

COPY allkeys.txt /app/data/allkeys.txt
COPY CollationTest_NON_IGNORABLE_SHORT.txt /app/data/CollationTest_NON_IGNORABLE_SHORT_raw.txt
COPY CollationTest_SHIFTED_SHORT.txt /app/data/CollationTest_SHIFTED_SHORT_raw.txt
COPY filter_tests.py /tmp/filter_tests.py
RUN python3 /tmp/filter_tests.py && rm /tmp/filter_tests.py

WORKDIR /app
