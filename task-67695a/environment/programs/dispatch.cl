class Animal inherits IO {
    sound() : String { "..." };
    speak() : Object {
        {
            out_string(sound());
            out_string("\n");
        }
    };
};

class Dog inherits Animal {
    sound() : String { "Woof" };
};

class Cat inherits Animal {
    sound() : String { "Meow" };
};

class Base inherits IO {
    describe() : Object {
        out_string("I am Base\n")
    };
};

class Derived inherits Base {
    describe() : Object {
        out_string("I am Derived\n")
    };
};

class A {
    a : Int <- 1;
    getA() : Int { a };
};

class B inherits A {
    b : Int <- a + 10;
    getB() : Int { b };
};

class C inherits B {
    c : Int <- b * 2;
    getC() : Int { c };
};

class Main inherits IO {
    main() : Object {
        {
            (new Animal).speak();
            (new Dog).speak();
            (new Cat).speak();
            let d : Derived <- new Derived in
            {
                d.describe();
                d@Base.describe();
            };
            let obj : C <- new C in
            {
                out_int(obj.getA());
                out_string(" ");
                out_int(obj.getB());
                out_string(" ");
                out_int(obj.getC());
                out_string("\n");
            };
        }
    };
};
