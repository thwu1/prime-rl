class A {
    name() : String { "A" };
};
class B inherits A {
    name() : String { "B" };
};
class C inherits B {
    name() : String { "C" };
};
class D inherits B {
    name() : String { "D" };
};

class Main inherits IO {
    test(x : A) : Object {
        case x of
            c : C => out_string("Matched C: ".concat(c.name()).concat("\n"));
            a : A => out_string("Matched A: ".concat(a.name()).concat("\n"));
            b : B => out_string("Matched B: ".concat(b.name()).concat("\n"));
        esac
    };
    main() : Object {
        {
            test(new A);
            test(new B);
            test(new C);
            test(new D);
        }
    };
};
