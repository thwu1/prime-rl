FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder


RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY v2_src/ /build/v2/
COPY app_src/legacy_app.c /build/app/legacy_app.c

RUN cd /build/v2 && \
    gcc -fPIC -c processor_v2.c -o processor_v2.o && \
    gcc -shared -Wl,-soname,libprocessor.so.2 -o libprocessor.so.2 processor_v2.o

RUN cd /build/app && \
    gcc -c legacy_app.c -o legacy_app.o -I/build/v2 && \
    gcc -o legacy_app legacy_app.o /build/v2/libprocessor.so.2 -Wl,-rpath,/app && \
    strip legacy_app

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    binutils \
    file \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/app/legacy_app /app/legacy_app
COPY v2_src/processor_v2.h /app/libprocessor_v2.h
COPY v5_src/ /app/libprocessor_v5/
COPY test_data.csv /app/test_data.csv

WORKDIR /app
