FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install DuckDB - core task dependency
RUN pip3 install duckdb==1.1.3

# Set up task workspace
WORKDIR /app

# Copy format reference and test files
COPY format_ref.md /app/FORMAT_REF.md
COPY test_files/ /app/test_files/
