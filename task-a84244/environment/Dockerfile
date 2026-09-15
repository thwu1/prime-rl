FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y --no-install-recommends \
    ocaml \
    ocaml-dune \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY dune-project /app/dune-project
COPY dune /app/dune
COPY triint64.mli /app/triint64.mli
COPY triint64.ml /app/triint64.ml
COPY main.ml /app/main.ml

WORKDIR /app
