
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install tree-sitter==0.25.2 \
    tree-sitter-python==0.25.0 \
    tree-sitter-java==0.23.5 \
    tree-sitter-javascript==0.25.0 \
    tree-sitter-typescript==0.23.2

RUN mkdir -p /app/queries /app/samples

COPY queries/python.scm /app/queries/python.scm
COPY queries/java.scm /app/queries/java.scm
COPY queries/javascript.scm /app/queries/javascript.scm
COPY queries/typescript.scm /app/queries/typescript.scm

COPY samples/python_sample.py /app/samples/python_sample.py
COPY samples/java_sample.java /app/samples/java_sample.java
COPY samples/javascript_sample.js /app/samples/javascript_sample.js
COPY samples/typescript_sample.ts /app/samples/typescript_sample.ts

WORKDIR /app
