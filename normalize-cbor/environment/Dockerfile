FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip xxd jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/encoders /app/rfc_notes /app/test_vectors /app/corpus

COPY alpha.py /app/encoders/alpha.py
COPY beta.py /app/encoders/beta.py
COPY gamma.py /app/encoders/gamma.py
COPY deterministic.md /app/rfc_notes/deterministic.md
COPY test_vectors.json /app/test_vectors/appendix_a.json
COPY corpus_gen.py /tmp/corpus_gen.py

RUN python3 /tmp/corpus_gen.py && rm /tmp/corpus_gen.py
RUN chmod +x /app/encoders/*.py

WORKDIR /app
