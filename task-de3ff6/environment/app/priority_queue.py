
"""
Max-heap priority queue.
Based on Siek's Essentials of Compilation support code.
"""


class PriorityQueue:
    def __init__(self, less):
        self.heap = Heap([], less, _update_position)
        self.get_key_and_pos = {}

    def push(self, key):
        kp = _KeyWithPosition(key)
        self.get_key_and_pos[key] = kp
        self.heap.insert(kp)

    def pop(self):
        return self.heap.extract_max().key

    def increase_key(self, key):
        obj = self.get_key_and_pos[key]
        _heap_increase_key(self.heap, obj.position)

    def empty(self):
        return self.heap.heap_size == 0

    def __len__(self):
        return self.heap.heap_size


class _KeyWithPosition:
    def __init__(self, k):
        self.key = k
        self.position = -1

    def __repr__(self):
        return str(self.key) + '@' + repr(self.position)


def _update_position(key_with_pos, pos):
    key_with_pos.position = pos


def _left(i):
    return 2 * i + 1


def _right(i):
    return 2 * (i + 1)


def _parent(i):
    return (i - 1) // 2


class Heap:
    def __init__(self, data, less, update):
        self.data = list(data)
        self.less = less
        self.update = update
        for i, obj in enumerate(self.data):
            self.update(obj, i)
        self.heap_size = len(self.data)
        self._build_max_heap()

    def maximum(self):
        return self.data[0]

    def insert(self, obj):
        self.heap_size += 1
        if len(self.data) < self.heap_size:
            self.data.append(obj)
        else:
            self.data[self.heap_size - 1] = obj
        self.update(obj, self.heap_size - 1)
        _heap_increase_key(self, self.heap_size - 1)

    def extract_max(self):
        assert self.heap_size != 0
        mx = self.data[0]
        self.data[0] = self.data[self.heap_size - 1]
        self.update(self.data[0], 0)
        self.heap_size -= 1
        self._max_heapify(0)
        return mx

    def _max_heapify(self, i):
        l = _left(i)
        r = _right(i)
        largest = i
        if l < self.heap_size and self.less(self.data[i], self.data[l]):
            largest = l
        if r < self.heap_size and self.less(self.data[largest], self.data[r]):
            largest = r
        if largest != i:
            self.data[i], self.data[largest] = self.data[largest], self.data[i]
            self.update(self.data[i], i)
            self.update(self.data[largest], largest)
            self._max_heapify(largest)

    def _build_max_heap(self):
        for i in range(len(self.data) // 2, -1, -1):
            self._max_heapify(i)


def _heap_increase_key(H, i):
    while i > 0 and H.less(H.data[_parent(i)], H.data[i]):
        pi = _parent(i)
        H.data[i], H.data[pi] = H.data[pi], H.data[i]
        H.update(H.data[i], i)
        H.update(H.data[pi], pi)
        i = pi
