#include "parser/parser.h"
#include "executor/executor.h"
#include <iostream>
#include <iomanip>

int main() {
    Parser parser;
    auto parsed = parser.parse("1.0 2.0 3.0 4.0 5.0");

    std::cout << "Parsed: " << parsed.name
              << " (" << parsed.rows() << " values)" << std::endl;

    Executor executor;
    auto result = executor.run(parsed);

    std::cout << "Executed: " << result.name
              << " (" << result.rows() << " values)" << std::endl;
    std::cout << "Pipeline complete" << std::endl;

    return 0;
}
