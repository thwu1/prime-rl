FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    gdb \
    xxd \
    binutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy format spec
COPY format_spec.txt /app/format_spec.txt

# Set up C parsing tool
RUN mkdir -p /app/tools
COPY scs_parse.c /app/tools/scs_parse.c
COPY tools_Makefile /app/tools/Makefile
RUN make -C /app/tools

# Generate binary dump files
COPY gen_dumps.py /tmp/gen_dumps.py
RUN python3 /tmp/gen_dumps.py && rm /tmp/gen_dumps.py

# Create results directory
RUN mkdir -p /app/results
