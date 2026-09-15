class Main inherits IO {
    main() : Object {
        let s : String <- "Hello, World!" in
        {
            out_int(s.length());
            out_string("\n");
            out_string(s.substr(0, 5));
            out_string("\n");
            out_string(s.substr(7, 5));
            out_string("\n");
            out_string(s.concat(" Cool!"));
            out_string("\n");
            out_string("abc".concat("def").concat("ghi"));
            out_string("\n");
            out_int("".length());
            out_string("\n");
        }
    };
};
