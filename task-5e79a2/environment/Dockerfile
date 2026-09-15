
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip curl && rm -rf /var/lib/apt/lists/*

RUN GOARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://go.dev/dl/go1.22.2.linux-${GOARCH}.tar.gz" -o /tmp/go.tar.gz && \
    tar -C /usr/local -xzf /tmp/go.tar.gz && \
    rm /tmp/go.tar.gz
ENV PATH=/usr/local/go/bin:$PATH

WORKDIR /app

COPY go.mod /app/go.mod

COPY pkg/base/client.go /app/pkg/base/client.go
COPY pkg/base/command.go /app/pkg/base/command.go
COPY pkg/base/event.go /app/pkg/base/event.go
COPY pkg/base/message.go /app/pkg/base/message.go
COPY pkg/base/node.go /app/pkg/base/node.go
COPY pkg/base/search.go /app/pkg/base/search.go
COPY pkg/base/state.go /app/pkg/base/state.go
COPY pkg/base/timer.go /app/pkg/base/timer.go
COPY pkg/base/util.go /app/pkg/base/util.go

COPY pkg/paxos/message.go /app/pkg/paxos/message.go
COPY pkg/paxos/timer.go /app/pkg/paxos/timer.go
COPY pkg/paxos/server.go /app/pkg/paxos/server.go
COPY pkg/paxos/helpers.go /app/pkg/paxos/helpers.go
COPY pkg/paxos/analyzer.go /app/pkg/paxos/analyzer.go
COPY pkg/paxos/predicates.go /app/pkg/paxos/predicates.go
COPY pkg/paxos/paxos_test.go /app/pkg/paxos/paxos_test.go
COPY pkg/paxos/verification_test.go /app/pkg/paxos/verification_test.go
