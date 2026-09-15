FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Task environment: binary analysis tools, SQLite, graph rendering, Python
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        xxd \
        sqlite3 \
        graphviz \
    && rm -rf /var/lib/apt/lists/*

# Generate the task environment files (binary ROM, SQLite DB, etc.)
COPY generate_rom.py /tmp/generate_rom.py
RUN python3 /tmp/generate_rom.py && rm /tmp/generate_rom.py

# Remove expected answers (tests have them hardcoded)
RUN rm -f /app/.expected_answers.json

WORKDIR /app

