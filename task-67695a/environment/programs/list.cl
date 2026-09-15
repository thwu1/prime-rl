class List {
    isNil() : Bool { true };
    head() : Int { { abort(); 0; } };
    tail() : List { { abort(); self; } };
    cons(i : Int) : List {
        (new Cons).init(i, self)
    };
};

class Cons inherits List {
    car : Int;
    cdr : List;

    isNil() : Bool { false };
    head() : Int { car };
    tail() : List { cdr };

    init(i : Int, rest : List) : List {
        {
            car <- i;
            cdr <- rest;
            self;
        }
    };
};

class Main inherits IO {
    print_list(l : List) : Object {
        if l.isNil() then
            out_string("")
        else
            {
                out_int(l.head());
                if l.tail().isNil() then
                    out_string("")
                else
                    {
                        out_string(" ");
                        print_list(l.tail());
                    }
                fi;
            }
        fi
    };

    sum_list(l : List) : Int {
        if l.isNil() then 0
        else l.head() + sum_list(l.tail())
        fi
    };

    reverse(l : List) : List {
        let result : List <- new List in
        {
            let current : List <- l in
                while not current.isNil() loop
                {
                    result <- result.cons(current.head());
                    current <- current.tail();
                }
                pool;
            result;
        }
    };

    main() : Object {
        let l : List <- (new List).cons(1).cons(2).cons(3).cons(4).cons(5) in
        {
            print_list(l);
            out_string("\n");
            out_string("Sum: ");
            out_int(sum_list(l));
            out_string("\n");
            out_string("Reversed: ");
            print_list(reverse(l));
            out_string("\n");
            out_string("Length: ");
            out_int(sum_list(
                (new List).cons(1).cons(1).cons(1).cons(1).cons(1)
            ));
            out_string("\n");
        }
    };
};
