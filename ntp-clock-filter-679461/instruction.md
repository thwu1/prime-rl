The directory `/app/` contains a multi-file C project that implements an NTPv4 multi-peer clock synchronization pipeline per RFC 5905. It reads peer definitions and exchange records from an input file, processes each peer's samples, selects the best peers, and produces system clock variables. The project compiles but produces incorrect output due to bugs and incomplete implementations spread across multiple source files.

Fix all bugs and complete all stub implementations so that:

```
make -C /app clean && make -C /app && /app/ntp_pipeline /app/peers_input.txt /app/output.txt
```

produces numerically correct results consistent with RFC 5905.

**Input** (`/app/peers_input.txt`, provided): `PEER <id> <stratum> <rootdelay> <rootdisp>` lines define peers; `XCHG <peer_id> <T1> <T2> <T3> <T4> <precision> <poll>` lines provide exchange timestamps as 16-hex-char NTP 64-bit values.

**Required output** (`/app/output.txt`):
```
PEER <id> %.9f %.9f %.9f %.9f %.9f <selected|rejected>
SYSTEM %.9f %.9f %.9f %.9f %d
```
Per peer: offset, delay, dispersion, jitter, root synchronization distance, and whether the peer survived selection. System line: combined offset, combined jitter, root delay, root dispersion, number of survivors.

**Success criteria:** All per-peer values and system variables must match a reference implementation of the complete RFC 5905 pipeline within 1e-6 relative tolerance. Peers with large offset deviations from the majority must be correctly rejected. The combined system offset must reflect the true clock offset, not be corrupted by outliers. The input data contains 6 peers (4 with consistent offsets near ~5ms, 2 with large deviations). Expect 3-4 survivors after peer selection.

**Constants** (defined in `ntp_types.h`): NSTAGE=8, MAXDISP=16, MAXDIST=1, PHI=15e-6, PRECISION=-20, NMIN=3, NSANE=1, MINDISP=0.01.

Source files: `ntp_types.h`, `ntp_ts.c/.h`, `ntp_filter.c/.h`, `ntp_select.c/.h`, `ntp_pipeline.c`. Do not modify the `Makefile` or `peers_input.txt`.
