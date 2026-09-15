# Proposed Configuration Changes

Review each proposal and provide an ACCEPT or REJECT verdict.

## Proposal A
**Target**: Topic `compliance-audit`
**Change**: Set `unclean.leader.election.enable=true`
**Rationale**: Reduce downtime during broker failures by allowing out-of-sync replicas to become leader.

## Proposal B
**Target**: Topic `payment-ledger`
**Change**: Set `min.insync.replicas=2` combined with `acks=all` (replication.factor=3)
**Rationale**: Strengthen write durability guarantees for financial transaction data.

## Proposal C
**Target**: Producer configuration
**Change**: Set `enable.idempotence=true` with `acks=1`
**Rationale**: Enable idempotent production while keeping latency low by only waiting for leader acknowledgment.

## Proposal D
**Target**: Topic `sensor-telemetry`
**Change**: Set `retention.ms=-1` (infinite retention)
**Rationale**: Preserve all historical sensor data for future machine learning model training.

## Proposal E
**Target**: Producer `throughput-producer`
**Change**: Set `compression.type=lz4` and `batch.size=262144`
**Rationale**: Improve throughput by using fast compression and larger batch sizes.
