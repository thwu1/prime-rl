class A {};
class B inherits A {};
class C inherits A {};

class Main {
    main() : Object {
        let x : A <- new B in
            case x of
                b : B => "is B";
                c : C => "is C";
            esac
    };
};
