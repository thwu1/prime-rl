FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/spec /app/grammars

COPY spec/cfg_format.md /app/spec/cfg_format.md
COPY grammars/g1_arith.cfg /app/grammars/g1_arith.cfg
COPY grammars/g2_epsilon.cfg /app/grammars/g2_epsilon.cfg
COPY grammars/g3_lvalue.cfg /app/grammars/g3_lvalue.cfg
COPY grammars/g4_decls.cfg /app/grammars/g4_decls.cfg

WORKDIR /app
