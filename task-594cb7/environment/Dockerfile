FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/histories /app/graphs

COPY spec.md /app/spec.md
COPY histories/h1.edn /app/histories/h1.edn
COPY histories/h2.edn /app/histories/h2.edn
COPY histories/h3.edn /app/histories/h3.edn
COPY histories/h4.edn /app/histories/h4.edn
COPY histories/h5.edn /app/histories/h5.edn
COPY histories/h6.edn /app/histories/h6.edn

WORKDIR /app
