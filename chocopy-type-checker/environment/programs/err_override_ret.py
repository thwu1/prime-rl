class A(object):
    def foo(self: "A") -> int:
        return 1

class B(A):
    def foo(self: "B") -> str:
        return "hello"
