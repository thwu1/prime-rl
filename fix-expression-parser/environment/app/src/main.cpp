
#include "expr_lang.h"
#include <iostream>

int main() {
    std::string input;
    std::string line;
    while (std::getline(std::cin, line)) {
        input += line + "\n";
    }

    try {
        Parser parser(input);
        parser.run();
    } catch (const ParseError& e) {
        std::cerr << "Unhandled error at " << e.line << ":" << e.col
                  << ": " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
