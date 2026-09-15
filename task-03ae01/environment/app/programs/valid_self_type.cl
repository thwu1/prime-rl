class Animal {
    copy_self(): SELF_TYPE { self };
};

class Dog inherits Animal {
    bark(): String { "Woof" };
};

class Main {
    main(): Object {
        let d: Dog <- (new Dog).copy_self() in
            d.bark()
    };
};
