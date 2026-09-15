"""Priority queue backed by a max-heap.

Supports push, pop (extract-max), and increase_key operations.
Useful for implementing the DSATUR graph coloring algorithm
with saturation-based priority.
"""


class PriorityQueue:
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
        heap_increase_key(self.heap, obj.position)

    def empty(self):
        return self.heap.heap_size == 0


class KeyWithPosition:
    def __init__(self, k):
        self.key = k
        self.position = -1

    def __repr__(self):
        return str(self.key) + '@' + repr(self.position)


def update_position(key_with_pos, pos):
    key_with_pos.position = pos


class Heap:
    def __init__(self, data, less, update):
        self.data = data
        self.less = less
        self.update = update
        i = 0
        for obj in self.data:
            self.update(obj, i)
            i += 1
        build_max_heap(self)

    def __repr__(self):
        return repr(self.data[:self.heap_size])

    def maximum(self):
        return self.data[0]

    def insert(self, obj):
        self.heap_size += 1
        if len(self.data) < self.heap_size:
            self.data.append(obj)
        else:
            self.data[self.heap_size - 1] = obj
        self.update(obj, self.heap_size - 1)
        heap_increase_key(self, self.heap_size - 1)

    def extract_max(self):
        assert self.heap_size != 0
        max_val = self.data[0]
        self.data[0] = self.data[self.heap_size - 1]
        self.update(self.data[0], 0)
        self.heap_size -= 1
        max_heapify(self, 0)
        return max_val


def left(i):
    return 2 * i + 1


def right(i):
    return 2 * (i + 1)


def parent(i):
    return (i - 1) // 2


def swap(A, i, j):
    tmp = A[i]
    A[i] = A[j]
    A[j] = tmp


def heap_increase_key(H, i):
    while i > 0 and H.less(H.data[parent(i)], H.data[i]):
        swap(H.data, i, parent(i))
        H.update(H.data[i], i)
        H.update(H.data[parent(i)], parent(i))
        i = parent(i)


def max_heapify(H, i):
    l = left(i)
    r = right(i)
    if l < H.heap_size and H.less(H.data[i], H.data[l]):
        largest = l
    else:
        largest = i
    if r < H.heap_size and H.less(H.data[largest], H.data[r]):
        largest = r
    if largest != i:
        swap(H.data, i, largest)
        H.update(H.data[i], i)
        H.update(H.data[largest], largest)
        max_heapify(H, largest)


def build_max_heap(H):
    H.heap_size = len(H.data)
    last_parent = len(H.data) // 2
    for i in range(last_parent, -1, -1):
        max_heapify(H, i)
