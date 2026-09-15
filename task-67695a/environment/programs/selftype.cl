class Counter inherits IO {
    count : Int <- 0;

    inc() : SELF_TYPE {
        {
            count <- count + 1;
            self;
        }
    };

    value() : Int { count };
};

class NamedCounter inherits Counter {
    name : String;

    setName(n : String) : SELF_TYPE {
        {
            name <- n;
            self;
        }
    };

    getName() : String { name };
};

class Cloneable inherits IO {
    x : Int <- 0;

    setX(v : Int) : SELF_TYPE {
        {
            x <- v;
            self;
        }
    };

    getX() : Int { x };

    makeNew() : SELF_TYPE {
        new SELF_TYPE
    };
};

class Special inherits Cloneable {
    label() : String { "special" };
};

class Main inherits IO {
    main() : Object {
        {
            let nc : NamedCounter <- (new NamedCounter).setName("test").inc().inc().inc() in
            {
                out_string(nc.getName());
                out_string(": ");
                out_int(nc.value());
                out_string("\n");
            };
            let s : Special <- (new Special).setX(42),
                s2 : Cloneable <- s.makeNew() in
            {
                out_int(s.getX());
                out_string("\n");
                case s2 of
                    sp : Special => out_string("Is Special\n");
                    cl : Cloneable => out_string("Is Cloneable\n");
                esac;
            };
        }
    };
};
