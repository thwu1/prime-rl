The file `/app/cubic.py` implements the CUBIC congestion control algorithm (RFC 8312bis / draft-ietf-tcpm-rfc8312bis) as used in production QUIC transport stacks. The implementation contains multiple bugs in the core congestion control mathematics that cause incorrect congestion window evolution.

Fix all bugs in `/app/cubic.py`. The corrected implementation must produce correct behavior for:

- **K computation** (Eq. 2): the time for the CUBIC window function to reach the previous maximum window size
- **Multiplicative decrease and fast convergence** (Section 4.6): window reduction and W_max adjustment when repeated losses occur before full recovery
- **TCP-friendly AIMD estimate** (Eq. 4): the W_est fallback window and its per-ACK increment, ensuring the CUBIC sender is never less aggressive than standard TCP Reno
- **Alpha adaptation**: transitioning alpha_aimd when the estimated window reaches the previous maximum

Run `python3 /app/simulate.py` to exercise the implementation and inspect results written to `/app/results/simulation.json`.