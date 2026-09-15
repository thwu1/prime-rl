
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    flex \
    bison \
    gcc \
    make \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /app/sample_programs

COPY tac_parser.py /app/tac_parser.py
COPY cfg.py /app/cfg.py
COPY main.py /app/main.py
COPY optimizer_stub.py /app/optimizer.py
COPY dot_output_stub.py /app/dot_output.py
COPY scanner.l /app/scanner.l
COPY parser.y /app/parser.y
COPY Makefile.app /app/Makefile
COPY simple.dcf /app/sample_programs/simple.dcf
COPY precedence.dcf /app/sample_programs/precedence.dcf
COPY control.dcf /app/sample_programs/control.dcf

WORKDIR /app
