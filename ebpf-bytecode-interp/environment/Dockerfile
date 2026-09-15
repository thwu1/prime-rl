FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    clang llvm binutils \
    && rm -rf /var/lib/apt/lists/*

RUN for tool in clang llvm-objdump llvm-readelf llvm-objcopy; do \
        if [ ! -e "/usr/bin/$tool" ]; then \
            target=$(ls /usr/bin/${tool}-[0-9]* 2>/dev/null | sort -V | tail -1); \
            [ -n "$target" ] && ln -sf "$target" "/usr/bin/$tool"; \
        fi; \
    done

COPY simple.c arith.c branch.c loop.c bitmanip.c /tmp/bpf_src/

RUN mkdir -p /app/programs && \
    for f in /tmp/bpf_src/*.c; do \
        name=$(basename "$f" .c); \
        clang -target bpf -O2 -c "$f" -o "/app/programs/${name}.o"; \
    done && \
    rm -rf /tmp/bpf_src

COPY bpf_isa.txt /app/reference/bpf_isa.txt
COPY setup_env.py /tmp/setup_env.py
RUN python3 /tmp/setup_env.py && rm /tmp/setup_env.py

WORKDIR /app
