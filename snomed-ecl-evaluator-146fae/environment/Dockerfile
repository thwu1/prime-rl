FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip jq sqlite3 && \
    rm -rf /var/lib/apt/lists/*


COPY data/ /app/data/
COPY verhoeff_spec.txt /app/verhoeff_spec.txt
COPY ecl_grammar.abnf /app/ecl_grammar.abnf

WORKDIR /app
