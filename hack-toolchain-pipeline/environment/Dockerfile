FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

COPY pipeline_init.py /app/hack_pipeline.py
COPY optimizer_stub.py /app/optimizer.py
COPY hack_spec.txt /app/docs/hack_spec.txt
COPY vm_programs/ /app/vm_programs/
COPY asm_programs/ /app/asm_programs/
COPY reference/ /app/reference/
COPY tools/ /app/tools/

RUN chmod +x /app/tools/ref_emulator.py /app/tools/hack_diff.py

WORKDIR /app
