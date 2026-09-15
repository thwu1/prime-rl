FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    ocaml \
    ocaml-dune \
    menhir \
    libmenhir-ocaml-dev \
    ocaml-findlib \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY dune-project /app/dune-project
COPY lib/ /app/lib/
COPY bin/ /app/bin/
WORKDIR /app
