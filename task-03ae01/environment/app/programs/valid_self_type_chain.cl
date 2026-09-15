class Builder {
    name : String;
    set_name(n : String) : SELF_TYPE {
        {
            name <- n;
            self;
        }
    };
};

class AdvBuilder inherits Builder {
    extra : Int;
    set_extra(e : Int) : SELF_TYPE {
        {
            extra <- e;
            self;
        }
    };
};

class Main {
    main() : Object {
        (new AdvBuilder).set_name("test").set_extra(42)
    };
};
