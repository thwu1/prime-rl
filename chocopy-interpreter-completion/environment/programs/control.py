x:int = 10
if x > 5:
    print(1)
elif x > 3:
    print(2)
else:
    print(3)

if x < 5:
    print(4)
elif x > 15:
    print(5)
else:
    print(6)

i:int = 0
while i < 5:
    i = i + 1
print(i)

y:int = 0
y = 1 if x > 5 else 2
print(y)

z:bool = False
z = True and False
print(z)
z = True or False
print(z)
z = not False
print(z)
