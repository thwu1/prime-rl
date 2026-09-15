class Animal(object):
    def sound(self: "Animal") -> str:
        return "..."

    def describe(self: "Animal") -> object:
        print(self.sound())

class Dog(Animal):
    def sound(self: "Dog") -> str:
        return "Woof"

class Cat(Animal):
    def sound(self: "Cat") -> str:
        return "Meow"

a: Animal = None
a = Dog()
a.describe()
a = Cat()
a.describe()
