FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip make jq && rm -rf /var/lib/apt/lists/*


COPY chocopy_spec.md /app/chocopy_spec.md
COPY type_summary_format.md /app/type_summary_format.md
COPY programs/ /app/programs/
COPY reference_asts/ /app/reference_asts/
COPY Makefile.skeleton /app/Makefile.skeleton

WORKDIR /app
