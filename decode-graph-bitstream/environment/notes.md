# WGEF Compressed Graph — Technical Notes

## Overview

This file contains a directed graph compressed using a WebGraph-inspired
scheme that combines Elias-Fano indexing with reference-based adjacency
list compression. The format is designed for compact representation of
sparse graphs with locality in adjacency structure.

## File Structure

- **Bytes 0–3**: Magic identifier `WGEF` (ASCII)
- **Byte 4 onward**: MSB-first (big-endian) bitstream payload

Within each byte, bit 7 (most significant) is read first, proceeding
down to bit 0. Reading continues at bit 7 of the next byte.

## Bitstream Layout

The payload contains three sections in sequence:

### 1. Header

Three gamma-coded non-negative integers:
- **N**: total number of nodes in the graph
- **W**: reference window size (maximum backward reference distance)
- **K**: compression parameter for the variable-length code used to
  encode successor values

### 2. Elias-Fano Offset Index

An Elias-Fano encoded monotone sequence of **N** cumulative bit offsets.
Offset *i* gives the bit position (relative to the start of the node
data section) where node *i*'s encoding begins. The first offset is
always 0.

The Elias-Fano representation splits each value into lower and upper
parts for space-efficient storage of monotone integer sequences.

### 3. Node Data Section

Per-node compressed adjacency data, encoded sequentially for nodes
0 through N−1. Each node's encoding begins with its gamma-coded
out-degree. Nodes with degree 0 have no further data.

Non-empty nodes encode a gamma-coded **reference offset** *r*:
- **r = 0** — "direct mode": the successor list is encoded independently
  as gap-coded values using the variable-length code parameterized by K.
- **r > 0** — "copy mode": the successor list is partially derived from
  the previously-decoded node at position (current − *r*), using an
  alternating copy/skip block mechanism, supplemented by additional
  values.

## Toolkit

The C source code in `/app/tools/` implements all bitstream primitives
and three diagnostic utilities:

- **bitstream.h / bitstream.c** — Bitstream reader library implementing
  every code used in the format. This is the authoritative reference for
  the encoding algorithms.
- **header_info** — Dumps header fields and Elias-Fano index parameters.
- **ef_dump** — Decodes the full Elias-Fano offset index and outputs
  JSON with header, layout, and per-node bit offsets.
- **bitprobe** — Decodes individual codes (gamma, unary, zeta, minimal
  binary) at arbitrary bit positions in the bitstream.

Build with: `cd /app/tools && mkdir build && cd build && cmake .. && make`

## Query Types

The file `/app/data/queries.txt` contains queries about the decoded
graph (one per line):

- `NODES` — total number of nodes
- `EDGES` — total number of directed edges
- `OUTDEGREE v` — out-degree of node v
- `EDGE u v` — `1` if edge u→v exists, `0` otherwise
- `SUCCESSORS v` — space-separated sorted successor list, or `NONE`
- `MAX_DEGREE` — maximum out-degree across all nodes
- `ISOLATED_NODES` — count of nodes with out-degree 0
- `FIRST_SUCCESSOR_SUM` — sum of the smallest successor of every
  non-isolated node
- `IN_DEGREE v` — in-degree of node v
- `CHECKSUM` — XOR of (u × 31337 + v) over all edges (u, v)
- `TWO_HOP_REACH v` — count of distinct nodes reachable from v in
  exactly 1 or 2 hops, excluding v itself
