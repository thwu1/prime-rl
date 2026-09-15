class Animal {};

class Cat inherits Animal {
    purr() : String { "purr" };
};

class Dog inherits Animal {
    bark() : String { "woof" };
};

class Main {
    main() : Object {
        let x : Bool <- true in
            if x then new Cat else new Dog fi
    };
};
