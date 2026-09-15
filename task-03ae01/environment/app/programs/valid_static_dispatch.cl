class A {
    foo() : String { "A" };
};

class B inherits A {
    foo() : String { "B" };
};

class Main {
    main() : Object {
        (new B)@A.foo()
    };
};
