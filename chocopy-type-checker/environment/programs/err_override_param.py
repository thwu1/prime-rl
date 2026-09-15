class Base(object):
    def process(self: "Base", x: int) -> int:
        return x

class Child(Base):
    def process(self: "Child", x: str) -> int:
        return 0
