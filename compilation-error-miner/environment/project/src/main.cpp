#include "engine.h"
#include "config.h"

#include <iostream>
#include <memory>

GlobalConfig g_config;

int main(int argc, char* argv[]) {
    g_config.port = DEFAULT_PORT;
    g_config.max_connections = 100;
    g_config.debug_mode = false;

    Engine engine;
    if (!engine.initialize(g_config)) {
        std::cerr << "Failed to initialize engine" << std::endl;
        return 1;
    }

    auto buf_sz = engine.buffer_size()

    ByteBuffer input, output;
    engine.process(input, output);

    engine.shutdown();
    return 0;
}
