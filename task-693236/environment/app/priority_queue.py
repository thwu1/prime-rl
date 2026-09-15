
"""Max-heap priority queue for use in DSATUR graph coloring."""


class KeyWithPosition:
    def __init__(self, k):
        self.key = k
        self.position = -1

    def __repr__(self):
        return str(self.key) + '@' + repr(self.position)


def update_position(key_with_pos, pos):
    key_with_pos.position = pos


def left(i):
    return 2 * i + 1

def right(i):
    return 2 * (i + 1)

def parent(i):
    return (i - 1) // 2

def swap(A, i, j):
    A[i], A[j] = A[j], A[i]


class Heap:
    def __init__(self, data, less, update):
        self.data = list(data)
        self.less = less
        self.update = update
        for i, obj in enumerate(self.data):
            self.update(obj, i)
        self._build_max_heap()

    def __repr__(self):
        return repr(self.data[:self.heap_size])

    @property
    def maximum(self):
        return self.data[0]

    def insert(self, obj):
        self.heap_size += 1
        if len(self.data) < self.heap_size:
            self.data.append(obj)
        else:
            self.data[self.heap_size - 1] = obj
        self.update(obj, self.heap_size - 1)
        self._increase_key(self.heap_size - 1)

    def extract_max(self):
        assert self.heap_size > 0
        mx = self.data[0]
        self.data[0] = self.data[self.heap_size - 1]
        self.update(self.data[0], 0)
        self.heap_size -= 1
        self._max_heapify(0)
        return mx

    def _increase_key(self, i):
        while i > 0 and self.less(self.data[parent(i)], self.data[i]):
            swap(self.data, i, parent(i))
            self.update(self.data[i], i)
            self.update(self.data[parent(i)], parent(i))
            i = parent(i)

    def _max_heapify(self, i):
        l = left(i)
        r = right(i)
        largest = i
        if l < self.heap_size and self.less(self.data[i], self.data[l]):
            largest = l
        if r < self.heap_size and self.less(self.data[largest], self.data[r]):
            largest = r
        if largest != i:
            swap(self.data, i, largest)
            self.update(self.data[i], i)
            self.update(self.data[largest], largest)
            self._max_heapify(largest)

    def _build_max_heap(self):
        self.heap_size = len(self.data)
        last_parent = len(self.data) // 2
        for i in range(last_parent, -1, -1):
            self._max_heapify(i)


class PriorityQueue:
    """Max-priority queue backed by a binary heap.

    Args:
        less: comparison function less(a, b) -> bool on KeyWithPosition objects.
    """
    def __init__(self, less):
        self.heap = Heap([], less, update_position)
        self.get_key_and_pos = {}

    def __repr__(self):
        return repr(self.heap)

    def push(self, key):
        kp = KeyWithPosition(key)
        self.get_key_and_pos[key] = kp
        self.heap.insert(kp)

    def pop(self):
        return self.heap.extract_max().key

    def increase_key(self, key):
        obj = self.get_key_and_pos[key]
        self.heap._increase_key(obj.position)

    def empty(self):
        return self.heap.heap_size == 0
