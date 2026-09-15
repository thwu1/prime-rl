
from collections import OrderedDict
import config


class PagedMemoryManager:
    """GPU KV-cache memory with paged (block-based) allocation.

    KV cache is divided into fixed-size pages of PAGE_SIZE_TOKENS tokens each.
    Pages are individually evictable via LRU policy.  Evicted pages are
    conceptually swapped to remote memory at the calibrated bandwidth.

    The scheduler can query page-level state via get_page_count() and
    get_swap_cost() to make memory-aware scheduling decisions.
    """

    def __init__(self):
        self.total_pages = config.TOTAL_PAGES
        self.page_size = config.PAGE_SIZE_TOKENS
        self.bytes_per_token = config.KV_CACHE_BYTES_PER_TOKEN
        self.remote_bw = config.get_remote_bandwidth()

        # Page state
        self.free_pages = set(range(self.total_pages))
        self.request_pages = {}          # req_id -> [(page_id, tokens_used), ...]
        self.page_lru = OrderedDict()    # page_id -> req_id (LRU order)
        self.swapped_out = {}            # req_id -> num_tokens in remote memory

        # Cumulative statistics
        self.total_page_allocs = 0
        self.total_page_evictions = 0
        self.total_page_loads = 0
        self._frag_samples = []

    # ---- internal helpers ----

    def _transfer_time_ms(self, num_tokens: int) -> float:
        if num_tokens <= 0:
            return 0.0
        size_bytes = num_tokens * self.bytes_per_token
        return (size_bytes / (1024 * 1024)) / self.remote_bw * 1000.0

    def _evict_one_page(self):
        """Evict the LRU page. Returns (req_id, tokens_freed, time_cost_ms)."""
        if not self.page_lru:
            return None, 0, 0.0

        page_id, req_id = self.page_lru.popitem(last=False)

        tokens = 0
        if req_id in self.request_pages:
            pages = self.request_pages[req_id]
            for i, (pid, t) in enumerate(pages):
                if pid == page_id:
                    tokens = t
                    pages.pop(i)
                    if not pages:
                        del self.request_pages[req_id]
                    break

        self.free_pages.add(page_id)
        if tokens > 0:
            self.swapped_out[req_id] = self.swapped_out.get(req_id, 0) + tokens

        time_cost = self._transfer_time_ms(tokens)
        self.total_page_evictions += 1
        return req_id, tokens, time_cost

    # ---- public interface (called by Simulator) ----

    def load_request(self, request) -> float:
        """Ensure request's KV cache is fully GPU-resident.  Returns time cost ms."""
        needed_tokens = request.total_kv_tokens
        if needed_tokens == 0:
            return 0.0

        # Already fully loaded?
        current_tokens = 0
        if request.id in self.request_pages:
            current_tokens = sum(t for _, t in self.request_pages[request.id])
            for pid, _ in self.request_pages[request.id]:
                if pid in self.page_lru:
                    self.page_lru.move_to_end(pid)

        swapped = self.swapped_out.pop(request.id, 0)
        tokens_to_load = needed_tokens - current_tokens
        if tokens_to_load <= 0:
            return 0.0

        time_cost = 0.0
        pages_needed = (tokens_to_load + self.page_size - 1) // self.page_size

        # Make room
        while len(self.free_pages) < pages_needed and self.page_lru:
            _, _, ec = self._evict_one_page()
            time_cost += ec

        if request.id not in self.request_pages:
            self.request_pages[request.id] = []

        remaining = tokens_to_load
        allocated = 0
        while remaining > 0 and self.free_pages:
            page_id = self.free_pages.pop()
            toks = min(remaining, self.page_size)
            self.request_pages[request.id].append((page_id, toks))
            self.page_lru[page_id] = request.id
            remaining -= toks
            allocated += 1
            self.total_page_allocs += 1

        # Upload cost from remote memory
        if swapped > 0:
            time_cost += self._transfer_time_ms(min(swapped, tokens_to_load))
            self.total_page_loads += 1

        return time_cost

    def update_kv_cache(self, request) -> float:
        """Update after one token generated.  May allocate a new page.
        Returns additional time cost in ms (usually 0)."""
        if request.id not in self.request_pages:
            return 0.0

        pages = self.request_pages[request.id]
        if not pages:
            return 0.0

        last_pid, last_toks = pages[-1]
        if last_toks < self.page_size:
            # Room in current page
            pages[-1] = (last_pid, last_toks + 1)
            if last_pid in self.page_lru:
                self.page_lru.move_to_end(last_pid)
            return 0.0

        # Need a new page
        time_cost = 0.0
        if not self.free_pages:
            if not self.page_lru:
                return 0.0
            _, _, ec = self._evict_one_page()
            time_cost += ec

        if not self.free_pages:
            return time_cost  # safety fallback

        page_id = self.free_pages.pop()
        pages.append((page_id, 1))
        self.page_lru[page_id] = request.id
        self.total_page_allocs += 1
        return time_cost

    def free_request(self, request):
        """Release all GPU pages for a completed request."""
        if request.id in self.request_pages:
            for pid, _ in self.request_pages[request.id]:
                self.free_pages.add(pid)
                if pid in self.page_lru:
                    del self.page_lru[pid]
            del self.request_pages[request.id]
        self.swapped_out.pop(request.id, None)

    # ---- queries for the scheduler ----

    def get_page_count(self, request_id: int) -> int:
        """Number of GPU-resident pages for a request."""
        if request_id not in self.request_pages:
            return 0
        return len(self.request_pages[request_id])

    def get_swap_cost(self, request_id: int) -> float:
        """Estimated time (ms) to swap out all GPU-resident pages for a request."""
        if request_id not in self.request_pages:
            return 0.0
        total_tokens = sum(t for _, t in self.request_pages[request_id])
        return self._transfer_time_ms(total_tokens)

    @property
    def fragmentation(self) -> float:
        """Internal fragmentation ratio (0 = no waste, 1 = all waste)."""
        if not self.request_pages:
            return 0.0
        total_cap = 0
        total_used = 0
        for pages in self.request_pages.values():
            for _, tokens in pages:
                total_cap += self.page_size
                total_used += tokens
        return 1.0 - (total_used / total_cap) if total_cap > 0 else 0.0

    @property
    def utilization(self) -> float:
        """Fraction of total pages currently allocated."""
        return 1.0 - len(self.free_pages) / self.total_pages

    def sample_fragmentation(self):
        """Record current fragmentation for later analysis."""
        self._frag_samples.append(self.fragmentation)

    @property
    def avg_fragmentation(self) -> float:
        if not self._frag_samples:
            return 0.0
        return sum(self._frag_samples) / len(self._frag_samples)
