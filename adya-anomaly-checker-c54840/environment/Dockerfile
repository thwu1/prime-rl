FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    graphviz \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/histories

COPY histories/serializable.edn /app/histories/serializable.edn
COPY histories/g0.edn /app/histories/g0.edn
COPY histories/g1a.edn /app/histories/g1a.edn
COPY histories/g1b.edn /app/histories/g1b.edn
COPY histories/g1c.edn /app/histories/g1c.edn
COPY histories/g_single.edn /app/histories/g_single.edn
COPY histories/g2_item.edn /app/histories/g2_item.edn
COPY histories/complex.edn /app/histories/complex.edn
COPY histories/stress.edn /app/histories/stress.edn

WORKDIR /app
