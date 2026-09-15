a:[int] = None
a = [1, 2, 3, 4, 5]
print(a[0])
print(a[4])
print(len(a))

b:[int] = None
b = [6, 7]
c:[int] = None
c = a + b
print(len(c))
print(c[5])
print(c[6])

a[0] = 99
print(a[0])
print(c[0])

i:int = 0
s:int = 0
for i in a:
    s = s + i
print(s)
