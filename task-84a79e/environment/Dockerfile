
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/programs /app/expected_outputs

COPY app/ir_spec.md /app/ir_spec.md
COPY app/interpreter.py /app/interpreter.py

COPY app/programs/prog1.ir /app/programs/prog1.ir
COPY app/programs/prog2.ir /app/programs/prog2.ir
COPY app/programs/prog3.ir /app/programs/prog3.ir
COPY app/programs/prog4.ir /app/programs/prog4.ir
COPY app/programs/prog5.ir /app/programs/prog5.ir

COPY app/expected_outputs/prog1.out /app/expected_outputs/prog1.out
COPY app/expected_outputs/prog2.out /app/expected_outputs/prog2.out
COPY app/expected_outputs/prog3.out /app/expected_outputs/prog3.out
COPY app/expected_outputs/prog4.out /app/expected_outputs/prog4.out
COPY app/expected_outputs/prog5.out /app/expected_outputs/prog5.out

RUN chmod +x /app/interpreter.py

WORKDIR /app
