# Expert Parallelism Communication Performance Notes

## Overview

DeepEP's ElasticBuffer manages expert-parallel (EP) dispatch and combine
operations using dedicated streaming multiprocessors (SMs). The number of
SMs allocated to communication directly affects achievable bandwidth.

## SM Allocation Trade-offs

- More SMs allocated to EP communication yield higher dispatch/combine bandwidth
- Fewer SMs for EP leaves more SMs available for GEMM and attention computation
- Bandwidth exhibits diminishing returns at higher SM counts as NVLink saturates

## Measurement Data

The `ep_measurements` table in the benchmark database records measured dispatch
and combine bandwidth (in GB/s) at various SM allocations for each GPU model.
These measurements were taken using DeepEP's ElasticBuffer with NVLink in an
8-GPU scale-up topology.

## Dispatch Element Sizes

EP dispatch supports both BF16 (2 bytes per element) and FP8 (1 byte per
element) precision for the hidden-state tensors sent to experts. The combine
operation always uses BF16.

## Production Configuration

Deployments typically choose the minimum SM allocation that provides near-peak
bandwidth, maximizing the SMs available for compute. The standard production
threshold is 90% of peak measured dispatch bandwidth.
