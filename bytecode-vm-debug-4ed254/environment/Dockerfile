FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y golang-go python3-pip && rm -rf /var/lib/apt/lists/*
COPY go.mod /app/go.mod
COPY main.go /app/main.go
COPY parse.go /app/parse.go
COPY compile.go /app/compile.go
COPY vm.go /app/vm.go
COPY disasm.go /app/disasm.go
WORKDIR /app
