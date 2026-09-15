FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y \
    iverilog \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/rtl /app/tb /app/mutants

COPY spec.md /app/spec.md
COPY timer_apb.v /app/rtl/timer_apb.v
COPY mutant_1.v /app/mutants/mutant_1.v
COPY mutant_2.v /app/mutants/mutant_2.v
COPY mutant_3.v /app/mutants/mutant_3.v
COPY mutant_4.v /app/mutants/mutant_4.v
COPY mutant_5.v /app/mutants/mutant_5.v
COPY mutant_6.v /app/mutants/mutant_6.v
COPY mutant_7.v /app/mutants/mutant_7.v
COPY mutant_8.v /app/mutants/mutant_8.v
COPY sim.sh /app/sim.sh
COPY run_mutation_test.sh /app/run_mutation_test.sh
RUN chmod +x /app/sim.sh /app/run_mutation_test.sh

WORKDIR /app
