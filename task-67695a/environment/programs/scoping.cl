class Foo {
    x : Int;
    s : String;
    b : Bool;
    o : Object;

    getX() : Int { x };
    getS() : String { s };
    getB() : Bool { b };
    getO() : Object { o };
};

class Main inherits IO {
    x : Int <- 100;

    main() : Object {
        {
            let f : Foo <- new Foo in
            {
                out_int(f.getX());
                out_string(" '");
                out_string(f.getS());
                out_string("' ");
                if f.getB() then out_string("true ") else out_string("false ") fi;
                if isvoid f.getO() then out_string("void") else out_string("not-void") fi;
                out_string("\n");
            };
            out_int(x);
            out_string("\n");
            let x : Int <- 1 in
            {
                out_int(x);
                out_string("\n");
                let x : Int <- x + 10 in
                {
                    out_int(x);
                    out_string("\n");
                };
                out_int(x);
                out_string("\n");
            };
            out_int(x);
            out_string("\n");
        }
    };
};
