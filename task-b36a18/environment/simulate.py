"""CUBIC Congestion Control Simulation.

Runs a simulated QUIC connection exercising the CUBIC congestion
control algorithm through slow start, loss events, congestion
avoidance, and fast convergence phases. Outputs results as JSON.
"""


import json
import os
import sys

sys.path.insert(0, '/app')
from cubic import CubicCC, BETA_CUBIC, ALPHA_AIMD

MDS = 1200   # max datagram size (bytes)
RTT = 0.1    # round-trip time (seconds)


def run_simulation():
    cc = CubicCC(max_datagram_size=MDS)
    results = {}

    # Phase 1: Slow Start
    # Each ACK grows cwnd by one MSS
    for i in range(15):
        cc.on_ack(MDS, 0.0, RTT, RTT)
    results["cwnd_after_slow_start"] = cc.congestion_window

    # Phase 2: First congestion event (loss)
    t_loss1 = 0.2
    pre_loss1 = cc.congestion_window
    cc.on_congestion_event(t_loss1)
    results["pre_loss1_cwnd"] = pre_loss1
    results["cwnd_after_loss1"] = cc.congestion_window
    results["w_max_after_loss1"] = cc.cubic.w_max
    results["k_after_loss1"] = round(cc.cubic.k, 6)
    results["ssthresh_after_loss1"] = cc.ssthresh

    # Phase 3: Congestion avoidance (100 ACKs over ~10 seconds)
    for i in range(100):
        send_time = t_loss1 + 0.01 + i * RTT
        ack_time = send_time + RTT
        cc.on_ack(MDS, send_time, ack_time, RTT)
    results["cwnd_after_100_ca_acks"] = cc.congestion_window
    results["w_est_after_100_ca"] = round(cc.cubic.w_est, 2)

    # Phase 4: Second congestion event (should trigger fast convergence
    # if cwnd hasn't fully recovered to w_max)
    t_loss2 = t_loss1 + 0.01 + 100 * RTT + RTT
    pre_loss2 = cc.congestion_window
    cc.on_congestion_event(t_loss2)
    results["pre_loss2_cwnd"] = pre_loss2
    results["cwnd_after_loss2"] = cc.congestion_window
    results["w_max_fast_convergence"] = round(cc.cubic.w_max, 2)

    # Phase 5: Second congestion avoidance (100 ACKs)
    for i in range(100):
        send_time = t_loss2 + 0.01 + i * RTT
        ack_time = send_time + RTT
        cc.on_ack(MDS, send_time, ack_time, RTT)
    results["cwnd_after_second_ca"] = cc.congestion_window

    os.makedirs("/app/results", exist_ok=True)
    with open("/app/results/simulation.json", "w") as f:
        json.dump(results, f, indent=2)

    print("=== CUBIC Simulation Results ===")
    for k, v in results.items():
        print(f"  {k}: {v}")
    print(f"\nResults written to /app/results/simulation.json")


if __name__ == "__main__":
    run_simulation()
