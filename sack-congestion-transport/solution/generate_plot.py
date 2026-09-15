#!/usr/bin/env python3
"""
Run a benchmark transfer and produce gnuplot input data and script
for the congestion window timeline visualization.

"""

import sys
sys.path.insert(0, '/app')
sys.path.insert(1, '/opt/transport_lib')

from transport import ReliableSender, ReliableReceiver
from channel import LossyChannel
from harness import transfer

# Run a benchmark transfer with mild loss to produce interesting cwnd dynamics
data = bytes(range(256)) * 200  # 51.2 KB
channel = LossyChannel(loss_rate=0.05, delay_ms=10, jitter_ms=3, seed=12345)
config = {
    'mss': 500,
    'max_window': 32,
    'seq_bits': 16,
    'initial_timeout_ms': 1000,
    'recv_window': 64,
}

received, stats, elapsed = transfer(
    ReliableSender, ReliableReceiver, channel, data, config, timeout=60)

assert received == data, 'Benchmark transfer failed — data mismatch'

cwnd_log = stats['cwnd_log']

# Write cwnd data file for gnuplot
with open('/app/cwnd_data.dat', 'w') as f:
    f.write('# time_s cwnd\n')
    for t, cwnd in cwnd_log:
        f.write(f'{t:.6f} {cwnd:.2f}\n')

# Write gnuplot script
with open('/app/cwnd_plot.gp', 'w') as f:
    f.write('set terminal svg size 800,400 enhanced\n')
    f.write("set output '/app/cwnd_evolution.svg'\n")
    f.write("set title 'Congestion Window Evolution'\n")
    f.write("set xlabel 'Time (seconds)'\n")
    f.write("set ylabel 'cwnd (packets)'\n")
    f.write('set grid\n')
    f.write("plot '/app/cwnd_data.dat' using 1:2 with linespoints "
            "title 'cwnd' lw 2 pt 7 ps 0.5\n")

print(f'Benchmark: {len(data)} bytes in {elapsed:.2f}s, '
      f'{stats["retransmissions"]} retransmits, '
      f'{len(cwnd_log)} cwnd samples written to /app/cwnd_data.dat')
print('gnuplot script written to /app/cwnd_plot.gp')
