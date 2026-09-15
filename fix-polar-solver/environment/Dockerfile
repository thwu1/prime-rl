FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip jq sqlite3 make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/configs /app/scripts /app/build/extracted

COPY coefficients.json /app/coefficients.json
COPY polar_solver.py /app/polar_solver.py
COPY coefficient_designer.py /app/coefficient_designer.py
COPY design_spec.json /app/design_spec.json
COPY benchmark_schema.sql /app/benchmark_schema.sql
COPY matrix_specs.json /app/matrix_specs.json
COPY configs/schulz_classic.json /app/configs/schulz_classic.json
COPY configs/schulz_conservative.json /app/configs/schulz_conservative.json
COPY Makefile /app/Makefile
COPY scripts/extract.jq /app/scripts/extract.jq
COPY scripts/benchmark.py /app/scripts/benchmark.py
COPY scripts/stability.py /app/scripts/stability.py
COPY scripts/import_data.sh /app/scripts/import_data.sh
COPY scripts/report.jq /app/scripts/report.jq

WORKDIR /app
