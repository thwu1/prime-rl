class Counter(object):
    count: int = 0

    def increment(self: "Counter") -> object:
        self.count = self.count + 1

    def get(self: "Counter") -> int:
        return self.count

c: Counter = None
c = Counter()
c.increment()
c.increment()
print(c.get())
