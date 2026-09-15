FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip rustc && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pbt /app/quickcheck-src /app/qc-ref

COPY app/pbt/__init__.py /app/pbt/__init__.py
COPY app/pbt/gen.py /app/pbt/gen.py
COPY app/pbt/shrink.py /app/pbt/shrink.py
COPY app/pbt/engine.py /app/pbt/engine.py
COPY app/pbt/structured.py /app/pbt/structured.py
COPY app/targets.py /app/targets.py
COPY app/merge.py /app/merge.py
COPY app/quickcheck-src/arbitrary.rs /app/quickcheck-src/arbitrary.rs
COPY app/quickcheck-src/tester.rs /app/quickcheck-src/tester.rs
COPY app/qc-ref/qc_ref.rs /app/qc-ref/qc_ref.rs

WORKDIR /app
