(* A test of (* nested *) comments and escape sequences *)
class Main inherits IO {
    main() : Object {
        {
            out_string("Hello, World!\n");
            out_string("tab:\there\n");
            out_string("backslash:\\\n");
            out_string("quote:\"hi\"\n");
        }
    };
};
