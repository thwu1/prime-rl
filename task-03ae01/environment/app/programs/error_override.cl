class A {
    foo(x : Int) : Int { x };
};

class B inherits A {
    foo(x : String) : Int { 0 };
};

class Main {
    main() : Object { 0 };
};
