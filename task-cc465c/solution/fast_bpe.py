"""
Optimized BPE trainer using a doubly-linked list and max-heap with lazy deletion.

Instead of rescanning the entire token sequence on every merge iteration (O(N) per
merge, O(N*M) total), this implementation:

1. Maintains a doubly-linked list of tokens so merges are O(k) where k is the
   number of occurrences of the merged pair.
2. Tracks pair counts and occurrence positions in hash maps for O(1) lookup.
3. Uses a max-heap with lazy deletion for O(log P) best-pair retrieval.
4. Incrementally updates adjacent pair counts when a merge creates/destroys
   neighboring pairs.

Total complexity: O(N log N) amortized, vs O(N*M) for the naive version.
"""

import heapq


class FastBPETrainer:
    def train(self, text, num_merges):
        """
        Train BPE on text for num_merges steps.

        Returns:
            dict: {(int, int): int} mapping merged pairs to new token IDs
                  (starting at 256). Identical output to NaiveBPETrainer.train().
        """
        data = list(text.encode("utf-8"))
        n = len(data)

        if n < 2:
            return {}

        # --- Doubly-linked list via parallel arrays ---
        val = data[:]          # token value at each position
        nxt = list(range(1, n)) + [-1]  # next pointer (-1 = end)
        prv = [-1] + list(range(n - 1))  # prev pointer (-1 = start)
        alive = [True] * n     # whether position is still in the list

        # --- Pair index ---
        # pair_count: (a, b) -> current count
        # pair_pos:   (a, b) -> set of left-positions where this pair occurs
        pair_count = {}
        pair_pos = {}

        # Initialize by scanning the linked list left-to-right
        cur = 0
        while cur != -1:
            nx = nxt[cur]
            if nx != -1:
                p = (val[cur], val[nx])
                if p not in pair_count:
                    pair_count[p] = 0
                    pair_pos[p] = set()
                pair_count[p] += 1
                pair_pos[p].add(cur)
            cur = nxt[cur]

        # --- Max-heap: entries are (-count, min_position, pair) ---
        # min_position serves as tie-breaker to replicate the reference's
        # behavior: among pairs with equal count, the one whose leftmost
        # occurrence comes first wins (matches Python dict insertion order
        # in get_stats + max() semantics).
        heap = []
        for p, cnt in pair_count.items():
            if cnt > 0:
                heapq.heappush(heap, (-cnt, min(pair_pos[p]), p))

        merges = {}

        for merge_i in range(num_merges):
            # --- Find the best pair (highest count, leftmost for ties) ---
            best_pair = None
            while heap:
                neg_c, mpos, p = heapq.heappop(heap)
                cur_count = pair_count.get(p, 0)
                if cur_count <= 0:
                    continue  # pair no longer exists
                if cur_count != -neg_c:
                    # Stale count — re-push with correct values
                    actual_min = min(pair_pos[p])
                    heapq.heappush(heap, (-cur_count, actual_min, p))
                    continue
                # Count matches. Verify min_position is current.
                positions = pair_pos[p]
                actual_min = min(positions)
                if actual_min != mpos:
                    # Stale position — re-push
                    heapq.heappush(heap, (neg_c, actual_min, p))
                    continue
                best_pair = p
                break

            if best_pair is None:
                break  # no more pairs to merge

            new_id = 256 + merge_i

            # --- Merge all occurrences of best_pair, left-to-right ---
            # Sorting ensures left-to-right processing, matching the
            # reference's merge() function which scans left-to-right.
            positions = sorted(pair_pos.get(best_pair, set()))

            for pos in positions:
                # Skip if this position was consumed by an earlier merge
                # in this iteration (it was the right element of a pair)
                if not alive[pos]:
                    continue

                nx = nxt[pos]
                if nx == -1:
                    continue

                # Verify the pair still matches at this position
                if val[pos] != best_pair[0] or val[nx] != best_pair[1]:
                    continue

                pv = prv[pos]
                nnx = nxt[nx]

                # 1) Remove old left-adjacent pair: (val[pv], val[pos])
                if pv != -1:
                    old_p = (val[pv], val[pos])
                    pair_count[old_p] -= 1
                    pair_pos[old_p].discard(pv)

                # 2) Remove the merged pair at this position
                pair_count[best_pair] -= 1
                pair_pos[best_pair].discard(pos)

                # 3) Remove old right-adjacent pair: (val[nx], val[nnx])
                if nnx != -1:
                    old_p = (val[nx], val[nnx])
                    pair_count[old_p] -= 1
                    pair_pos[old_p].discard(nx)

                # 4) Perform the merge: pos absorbs nx
                val[pos] = new_id
                alive[nx] = False
                nxt[pos] = nnx
                if nnx != -1:
                    prv[nnx] = pos

                # 5) Add new left-adjacent pair: (val[pv], new_id)
                if pv != -1:
                    new_p = (val[pv], new_id)
                    if new_p not in pair_count:
                        pair_count[new_p] = 0
                        pair_pos[new_p] = set()
                    pair_count[new_p] += 1
                    pair_pos[new_p].add(pv)
                    heapq.heappush(
                        heap, (-pair_count[new_p], min(pair_pos[new_p]), new_p)
                    )

                # 6) Add new right-adjacent pair: (new_id, val[nnx])
                if nnx != -1:
                    new_p = (new_id, val[nnx])
                    if new_p not in pair_count:
                        pair_count[new_p] = 0
                        pair_pos[new_p] = set()
                    pair_count[new_p] += 1
                    pair_pos[new_p].add(pos)
                    heapq.heappush(
                        heap, (-pair_count[new_p], min(pair_pos[new_p]), new_p)
                    )

            merges[best_pair] = new_id

            # If the pair still has residual occurrences, re-push
            remaining = pair_count.get(best_pair, 0)
            if remaining > 0:
                heapq.heappush(
                    heap, (-remaining, min(pair_pos[best_pair]), best_pair)
                )

        return merges
