class LRUCache:
    """Least Recently Used cache with fixed capacity."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.cache = {}
        self.order = []

    def get(self, key):
        """Get value by key, return -1 if not found."""
        if key not in self.cache:
            return -1
        self.order.remove(key)
        self.order.append(key)
        return self.cache[key]

    def put(self, key, value):
        """Insert or update key-value pair, evicting LRU entry if at capacity."""
        if key in self.cache:
            self.order.remove(key)
        elif len(self.cache) >= self.capacity:
            oldest = self.order.pop()
            del self.cache[oldest]
        self.cache[key] = value
        self.order.append(key)

    def size(self):
        """Return current number of entries."""
        return len(self.cache)
