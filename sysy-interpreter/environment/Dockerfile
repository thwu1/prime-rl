
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    clang \
    llvm \
    && rm -rf /var/lib/apt/lists/*

RUN for tool in clang lli opt llvm-as llvm-link llvm-dis; do \
      command -v $tool > /dev/null 2>&1 || \
      { f=$(ls /usr/bin/${tool}-* 2>/dev/null | head -1); \
        [ -n "$f" ] && ln -sf "$f" /usr/bin/$tool; } || true; \
    done

COPY spec/ /app/spec/
COPY samples/ /app/samples/
COPY runtime/ /app/runtime/

RUN cd /app/runtime && \
    clang -shared -fPIC -o sylib.so sylib.c && \
    clang -c -emit-llvm -o sylib.bc sylib.c

WORKDIR /app
