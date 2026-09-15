FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY go.* ./
RUN go mod download
COPY . .
RUN go build -o worker .

FROM alpine:3.19
COPY --from=builder /build/worker /usr/local/bin/worker
CMD ["worker"]
