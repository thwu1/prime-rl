class Main inherits IO {
    main() : Object {
        let a : Int <- 0,
            b : Int <- 1,
            i : Int <- 0,
            temp : Int in
        {
            while i < 10 loop
            {
                if 0 < i then out_string(" ") else out_string("") fi;
                out_int(a);
                temp <- a + b;
                a <- b;
                b <- temp;
                i <- i + 1;
            }
            pool;
            out_string("\n");
        }
    };
};
