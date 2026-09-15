class Animal(object):
    sound:str = "..."

    def speak(self:"Animal") -> str:
        return self.sound

    def description(self:"Animal") -> str:
        return self.speak()

class Dog(Animal):
    def __init__(self:"Dog"):
        self.sound = "Woof"

class Cat(Animal):
    def __init__(self:"Cat"):
        self.sound = "Meow"

    def speak(self:"Cat") -> str:
        return "Cat says: " + self.sound

a:Animal = None
a = Dog()
print(a.speak())
print(a.description())
a = Cat()
print(a.speak())
print(a.description())

class A(object):
    def f(self:"A") -> int:
        return 1

    def g(self:"A") -> int:
        return self.f()

class B(A):
    def f(self:"B") -> int:
        return 2

class C(B):
    pass

x:A = None
x = A()
print(x.g())
x = B()
print(x.g())
x = C()
print(x.g())
