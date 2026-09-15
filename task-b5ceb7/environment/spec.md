# GPU Shared Memory Bank Conflict Model

## Overview

GPU shared memory is divided into equally-sized modules called **banks** that can be accessed simultaneously. When multiple threads in a warp access addresses that map to the same bank, the accesses must be serialized, creating **bank conflicts**. Understanding and analyzing bank conflicts is critical for optimizing GPU kernel performance.

## Memory Architecture

- **Number of banks**: 32
- **Bank width**: 4 bytes (32 bits)
- **Bank assignment**: For a given byte address `addr`, the bank index is computed as:

      bank(addr) = floor(addr / 4) mod 32

  Consecutive 4-byte words map to consecutive banks. The pattern wraps every 128 bytes (32 banks x 4 bytes).

## Warp Access Model

A warp consists of exactly 32 threads, indexed t=0 to t=31. When a shared memory instruction is executed, each thread specifies a byte address to access. All 32 accesses are evaluated together for bank conflicts.

## Conflict Analysis

Given a set of 32 byte addresses (one per thread), the analysis proceeds as follows:

1. **Bank mapping**: Compute the bank index for each thread's address using the formula above.

2. **Broadcast rule**: If multiple threads access the **exact same byte address**, this constitutes a **broadcast**. A broadcast does not create a bank conflict -- the hardware serves all threads reading the same address in a single transaction. When counting distinct addresses per bank, duplicate addresses count only once.

3. **Wavefronts**: For each bank, count the number of **distinct** byte addresses that map to it. The number of wavefronts (serialized memory transactions) for the entire warp is the **maximum** of these per-bank counts across all 32 banks:

       wavefronts = max over all banks of (number of distinct addresses in that bank)

   A bank with zero accesses contributes 0 to this maximum.

4. **Per-bank conflicts**: For a given bank, the number of conflicts is:

       conflicts(bank) = max(0, distinct_addresses_in_bank - 1)

5. **Total conflicts**: The sum of per-bank conflicts across all 32 banks:

       total_conflicts = sum over all banks of conflicts(bank)

6. **Conflict-free**: A memory access pattern is conflict-free if and only if wavefronts equals 1.

## Example

Consider 4 threads (of a 32-thread warp) accessing these byte addresses (other threads access unique banks not shown):

- Thread 0: addr=0 --> bank = floor(0/4) mod 32 = 0
- Thread 1: addr=128 --> bank = floor(128/4) mod 32 = floor(32) mod 32 = 0
- Thread 2: addr=4 --> bank = floor(4/4) mod 32 = 1
- Thread 3: addr=128 --> bank = floor(128/4) mod 32 = 0  (broadcast with thread 1)

Bank 0 distinct addresses: {0, 128} --> 2 distinct --> 1 conflict
Bank 1 distinct addresses: {4} --> 1 distinct --> 0 conflicts

Wavefronts = max(2, 1) = 2
Total conflicts = 1 + 0 = 1

Note: Threads 1 and 3 access the same address (128). This is a broadcast -- address 128 is counted only once in bank 0's distinct address set. Without the broadcast rule, one might incorrectly count 3 accesses to bank 0.
