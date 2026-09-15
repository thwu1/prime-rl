FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install liblouis braille translator, tools, and python3-pip
RUN apt-get update && \
    apt-get install -y \
        liblouis-bin \
        liblouis-data \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Set table search path for liblouis
ENV LOUIS_TABLEPATH=/usr/share/liblouis/tables

# Create task directory structure
RUN mkdir -p /app/tables /app/docs

# Copy the skeleton braille translation table (character definitions only, no rules)
COPY sci-notation.ctb /app/tables/sci-notation.ctb

# Copy opcode reference documentation
COPY opcodes.txt /app/docs/opcodes.txt

WORKDIR /app
