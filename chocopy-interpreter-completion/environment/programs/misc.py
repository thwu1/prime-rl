class Box(object):
    value:int = 0

a:Box = None
b:Box = None
print(a is None)
a = Box()
print(a is None)
b = a
print(a is b)
b = Box()
print(a is b)
print(None is None)

s:str = "abcde"
print(s[0])
print(s[4])
print(len(s))
c:str = ""
n:int = 0
for c in s:
    n = n + 1
print(n)
print(c)

p:int = 0
q:int = 0
p = q = 7
print(p)
print(q)
