"""
Optimized BPE tokenizer using doubly-linked lists and a max-heap
with lazy deletion for incremental pair frequency updates.
"""

import regex as re
import heapq
from collections import defaultdict

GPT4_SPLIT_PATTERN = r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+"""


class Node:
    """Doubly-linked list node representing a single token in a chunk."""
    __slots__ = ["token", "prev", "next", "pos"]

    def __init__(self, token, pos):
        self.token = token
        self.pos = pos
        self.prev = None
        self.next = None


class FastBPETrainer:
    def __init__(self, pattern=None):
        self.pattern = GPT4_SPLIT_PATTERN if pattern is None else pattern
        self.compiled_pattern = re.compile(self.pattern)
        self.merges = {}
        self.vocab = {idx: bytes([idx]) for idx in range(256)}

    def train(self, text, num_merges):
        """
        Train BPE with incremental pair-frequency updates.
        Produces identical merge sequences to NaiveBPETrainer.
        """
        text_chunks = re.findall(self.compiled_pattern, text)
        if not text_chunks:
            self.merges = {}
            self.vocab = {idx: bytes([idx]) for idx in range(256)}
            return []

        # -- Build linked lists and count initial pairs --
        node_registry = {}          # id(node) -> node
        pair_counts = defaultdict(int)
        pair_nodes = defaultdict(set)  # pair -> {id(left_node), ...}
        pos_counter = 0

        for chunk_text in text_chunks:
            chunk_bytes = chunk_text.encode("utf-8")
            if len(chunk_bytes) < 2:
                if len(chunk_bytes) == 1:
                    n = Node(chunk_bytes[0], pos_counter)
                    pos_counter += 1
                    node_registry[id(n)] = n
                continue

            ids = list(chunk_bytes)
            head = Node(ids[0], pos_counter)
            pos_counter += 1
            node_registry[id(head)] = head
            prev = head

            for t in ids[1:]:
                node = Node(t, pos_counter)
                pos_counter += 1
                node.prev = prev
                prev.next = node
                node_registry[id(node)] = node

                pair = (prev.token, node.token)
                pair_counts[pair] += 1
                pair_nodes[pair].add(id(prev))

                prev = node

        if not pair_counts:
            self.merges = {}
            self.vocab = {idx: bytes([idx]) for idx in range(256)}
            return []

        # -- Build max-heap: entries are (-count, pair) --
        heap = [(-c, p) for p, c in pair_counts.items()]
        heapq.heapify(heap)

        merges = {}
        vocab = {idx: bytes([idx]) for idx in range(256)}
        merge_list = []

        for i in range(num_merges):
            # Pop until we find a valid (non-stale) entry
            best_pair = None
            while heap:
                neg_c, p = heapq.heappop(heap)
                actual = pair_counts.get(p, 0)
                if actual > 0 and actual == -neg_c:
                    best_pair = p
                    break

            if best_pair is None:
                break

            new_token = 256 + i
            merges[best_pair] = new_token
            vocab[new_token] = vocab[best_pair[0]] + vocab[best_pair[1]]
            merge_list.append(best_pair)

            # Collect valid positions, sort L-to-R to match naive greedy order
            positions = pair_nodes.get(best_pair, set())
            valid = []
            for nid in positions:
                if nid in node_registry:
                    nd = node_registry[nid]
                    if (nd.next is not None
                            and nd.token == best_pair[0]
                            and nd.next.token == best_pair[1]):
                        valid.append(nd)
            valid.sort(key=lambda n: n.pos)

            # Clear tracking for the pair we are merging
            pair_nodes[best_pair] = set()
            pair_counts[best_pair] = 0

            consumed = set()  # ids of right-nodes already consumed

            for left in valid:
                if id(left) in consumed:
                    continue

                right = left.next
                if right is None:
                    continue
                if left.token != best_pair[0] or right.token != best_pair[1]:
                    continue  # invalidated by earlier merge in this batch

                prev_nd = left.prev
                next2 = right.next

                # Decrement old neighbour pairs and re-push updated counts
                if prev_nd is not None:
                    old_l = (prev_nd.token, left.token)
                    pair_counts[old_l] -= 1
                    pair_nodes[old_l].discard(id(prev_nd))
                    if pair_counts[old_l] > 0:
                        heapq.heappush(heap, (-pair_counts[old_l], old_l))

                if next2 is not None:
                    old_r = (right.token, next2.token)
                    pair_counts[old_r] -= 1
                    pair_nodes[old_r].discard(id(right))
                    if pair_counts[old_r] > 0:
                        heapq.heappush(heap, (-pair_counts[old_r], old_r))

                # Perform the merge: left absorbs right
                left.token = new_token
                left.next = next2
                if next2 is not None:
                    next2.prev = left

                del node_registry[id(right)]
                consumed.add(id(right))

                # Increment new neighbour pairs
                if prev_nd is not None:
                    nl = (prev_nd.token, new_token)
                    pair_counts[nl] += 1
                    pair_nodes[nl].add(id(prev_nd))
                    heapq.heappush(heap, (-pair_counts[nl], nl))

                if next2 is not None:
                    nr = (new_token, next2.token)
                    pair_counts[nr] += 1
                    pair_nodes[nr].add(id(left))
                    heapq.heappush(heap, (-pair_counts[nr], nr))

        self.merges = merges
        self.vocab = vocab
        return merge_list

    def encode(self, text):
        """Encode text to token ids using trained merges."""
        text_chunks = re.findall(self.compiled_pattern, text)
        all_ids = []
        for chunk in text_chunks:
            chunk_bytes = chunk.encode("utf-8")
            ids = list(chunk_bytes)
            while len(ids) >= 2:
                stats = {}
                for pair in zip(ids, ids[1:]):
                    stats[pair] = stats.get(pair, 0) + 1
                pair = min(stats, key=lambda p: self.merges.get(p, float("inf")))
                if pair not in self.merges:
                    break
                idx = self.merges[pair]
                newids = []
                j = 0
                while j < len(ids):
                    if (ids[j] == pair[0]
                            and j < len(ids) - 1
                            and ids[j + 1] == pair[1]):
                        newids.append(idx)
                        j += 2
                    else:
                        newids.append(ids[j])
                        j += 1
                ids = newids
            all_ids.extend(ids)
        return all_ids

    def decode(self, ids):
        """Decode token ids back to text."""
        text_bytes = b"".join(self.vocab[idx] for idx in ids)
        return text_bytes.decode("utf-8", errors="replace")
