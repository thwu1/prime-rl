FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    cargo \
    rustc \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY Cargo.toml /app/Cargo.toml
COPY Cargo.lock /app/Cargo.lock
COPY src/ /app/src/
COPY grammar.ebnf /app/grammar.ebnf
COPY input.txt /app/input.txt

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
