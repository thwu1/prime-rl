class A(object):
    pass

class B(A):
    pass

class C(A):
    pass

class D(B):
    pass

flag: bool = True
x: A = None
x = D() if flag else C()
y: object = None
y = B() if flag else C()
