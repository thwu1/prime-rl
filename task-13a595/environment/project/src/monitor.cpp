#include "netmon-v2/api.h"
#include "generated_config.h"
#include <iostream>
#include <string>

extern "C" {
    void netmon_print_info() {
        std::cout << "NetMon v" << NETMON_VERSION_STRING << std::endl;
        std::cout << "Build: " << NETMON_BUILD_HASH << std::endl;
    }
}
