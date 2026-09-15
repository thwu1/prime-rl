class Shape(object):
    def area(self: "Shape") -> int:
        return 0

class Rect(Shape):
    w: int = 0
    h: int = 0
    def __init__(self: "Rect"):
        self.w = 3
        self.h = 4
    def area(self: "Rect") -> int:
        return self.w * self.h

class Circle(Shape):
    r: int = 0
    def __init__(self: "Circle"):
        self.r = 5
    def area(self: "Circle") -> int:
        return self.r * self.r * 3

shapes: [Shape] = None
shapes = [Rect(), Circle()]
i: int = 0
s: Shape = None
for s in shapes:
    i = i + s.area()
print(i)
