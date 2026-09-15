# ChocoPy class definitions

class A(object):
    x: int = 0

    def __init__(self: "A"):
        pass

    def foo(self: "A", n: int) -> str:
        return ""

    def bar(self: "A") -> object:
        return None

class B(A):
    y: bool = False

    def __init__(self: "B"):
        pass

    def foo(self: "B", n: int) -> str:
        return ""

    def baz(self: "B", s: str) -> int:
        return 0

class C(A):
    z: str = ""

    def __init__(self: "C"):
        pass

    def bar(self: "C") -> object:
        return None

class D(B):
    w: int = 0

    def __init__(self: "D"):
        pass

    def qux(self: "D", a: A) -> bool:
        return True

class E(B):

    def __init__(self: "E"):
        pass

    def baz(self: "E", s: str) -> int:
        return 0

class F(object):
    val: int = 0

    def __init__(self: "F"):
        pass

    def compute(self: "F", a: int, b: int) -> int:
        return 0

class G(F):
    name: str = ""

    def __init__(self: "G"):
        pass

    def compute(self: "G", a: int, b: int) -> int:
        return 0
