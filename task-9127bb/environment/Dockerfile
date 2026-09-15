FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    golang-go \
    && rm -rf /var/lib/apt/lists/*

COPY go.mod /app/go.mod
COPY vm.go /app/vm.go
RUN cd /app && go build -o vm .

COPY asmcheck_src/main.go /app/asmcheck_src/main.go
COPY asmcheck_src/go.mod /app/asmcheck_src/go.mod
RUN cd /app/asmcheck_src && go build -o /app/asmcheck . && rm -rf /app/asmcheck_src

COPY spec.md /app/spec.md
COPY targets.json /app/targets.json
COPY programs/ /app/programs/
COPY inputs/ /app/inputs/

WORKDIR /app
