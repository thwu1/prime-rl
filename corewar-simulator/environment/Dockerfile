FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip gcc make && rm -rf /var/lib/apt/lists/*

COPY pmars_src/ /tmp/pmars_src/
RUN cd /tmp/pmars_src && \
    gcc -O -DEXT94 -DSERVER -DPERMUTATE -DRWLIMIT -o pmars \
    pmars.c asm.c eval.c disasm.c cdb.c sim.c pos.c clparse.c global.c token.c str_eng.c && \
    cp pmars /usr/local/bin/pmars && \
    chmod +x /usr/local/bin/pmars && \
    rm -rf /tmp/pmars_src

RUN mkdir -p /app/spec /app/warriors

COPY spec.txt /app/spec/icws94.txt
COPY imp.red /app/warriors/imp.red
COPY dwarf.red /app/warriors/dwarf.red
COPY target.red /app/warriors/target.red

WORKDIR /app
