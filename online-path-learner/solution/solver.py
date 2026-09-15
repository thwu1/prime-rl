#!/usr/bin/env python3
"""
Solver for the Online Shortest Path problem.

Strategy:
  - Maintain edge weight estimates (initialized to midpoint heuristic)
  - Use Dijkstra with current estimates + exploration bonus for under-observed edges
  - After each query, update estimates via multiplicative update with decaying alpha
  - Exploration bonus decays with observation count to encourage early coverage
"""

import sys
import heapq

ROWS = 30
COLS = 30
N = ROWS * COLS
INIT_WEIGHT = 5000.0


def main():
    h_est = [[INIT_WEIGHT] * (COLS - 1) for _ in range(ROWS)]
    v_est = [[INIT_WEIGHT] * COLS for _ in range(ROWS - 1)]

    h_cnt = [[0] * (COLS - 1) for _ in range(ROWS)]
    v_cnt = [[0] * COLS for _ in range(ROWS - 1)]

    for q_idx in range(1000):
        line = sys.stdin.readline()
        if not line:
            break
        parts = line.split()
        si, sj, ti, tj = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])

        src = si * COLS + sj
        dst = ti * COLS + tj

        dist = [float('inf')] * N
        prev_node = [-1] * N
        prev_dir = [None] * N
        dist[src] = 0.0
        pq = [(0.0, src)]

        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            if u == dst:
                break
            ui, uj = u // COLS, u % COLS

            if uj < COLS - 1:
                w = h_est[ui][uj]
                bonus = 0.2 / (1.0 + h_cnt[ui][uj] * 0.4)
                ew = w * (1.0 - bonus)
                nd = d + ew
                nxt = u + 1
                if nd < dist[nxt]:
                    dist[nxt] = nd
                    prev_node[nxt] = u
                    prev_dir[nxt] = 'R'
                    heapq.heappush(pq, (nd, nxt))

            if uj > 0:
                w = h_est[ui][uj - 1]
                bonus = 0.2 / (1.0 + h_cnt[ui][uj - 1] * 0.4)
                ew = w * (1.0 - bonus)
                nd = d + ew
                nxt = u - 1
                if nd < dist[nxt]:
                    dist[nxt] = nd
                    prev_node[nxt] = u
                    prev_dir[nxt] = 'L'
                    heapq.heappush(pq, (nd, nxt))

            if ui < ROWS - 1:
                w = v_est[ui][uj]
                bonus = 0.2 / (1.0 + v_cnt[ui][uj] * 0.4)
                ew = w * (1.0 - bonus)
                nd = d + ew
                nxt = u + COLS
                if nd < dist[nxt]:
                    dist[nxt] = nd
                    prev_node[nxt] = u
                    prev_dir[nxt] = 'D'
                    heapq.heappush(pq, (nd, nxt))

            if ui > 0:
                w = v_est[ui - 1][uj]
                bonus = 0.2 / (1.0 + v_cnt[ui - 1][uj] * 0.4)
                ew = w * (1.0 - bonus)
                nd = d + ew
                nxt = u - COLS
                if nd < dist[nxt]:
                    dist[nxt] = nd
                    prev_node[nxt] = u
                    prev_dir[nxt] = 'U'
                    heapq.heappush(pq, (nd, nxt))

        path_chars = []
        edge_list = []
        node = dst
        while node != src:
            direction = prev_dir[node]
            path_chars.append(direction)
            p = prev_node[node]
            pi, pj = p // COLS, p % COLS
            ni, nj = node // COLS, node % COLS

            if direction == 'R':
                edge_list.append(('h', pi, pj))
            elif direction == 'L':
                edge_list.append(('h', ni, nj))
            elif direction == 'D':
                edge_list.append(('v', pi, pj))
            elif direction == 'U':
                edge_list.append(('v', ni, nj))

            node = p

        path_chars.reverse()
        edge_list.reverse()

        sys.stdout.write(''.join(path_chars) + '\n')
        sys.stdout.flush()

        feedback_line = sys.stdin.readline()
        if not feedback_line:
            break
        feedback = int(feedback_line.strip())

        if not edge_list:
            continue

        est_total = 0.0
        for etype, ei, ej in edge_list:
            if etype == 'h':
                est_total += h_est[ei][ej]
            else:
                est_total += v_est[ei][ej]

        if est_total <= 0:
            continue

        ratio = feedback / est_total

        for etype, ei, ej in edge_list:
            if etype == 'h':
                h_cnt[ei][ej] += 1
                cnt = h_cnt[ei][ej]
                alpha = 0.5 / (1.0 + cnt * 0.15)
                h_est[ei][ej] *= 1.0 + alpha * (ratio - 1.0)
                h_est[ei][ej] = max(500.0, min(h_est[ei][ej], 12000.0))
            else:
                v_cnt[ei][ej] += 1
                cnt = v_cnt[ei][ej]
                alpha = 0.5 / (1.0 + cnt * 0.15)
                v_est[ei][ej] *= 1.0 + alpha * (ratio - 1.0)
                v_est[ei][ej] = max(500.0, min(v_est[ei][ej], 12000.0))


if __name__ == '__main__':
    main()
