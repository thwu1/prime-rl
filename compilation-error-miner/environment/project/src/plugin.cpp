#include "plugin.h"
#include "engine.h"

#include <dlfcn.h>
#include <iostream>

PluginManager::PluginManager(Engine& engine) : engine_(engine) {}

bool PluginManager::load(const std::string& path) {
    void* handle = dlopen(path.c_str(), RTLD_NOW);
    if (!handle) {
        std::cerr << "Failed to load plugin: " << dlerror() << std::endl;
        return false;
    }
    engine_.flush_buffer();
    return true;
}

void PluginManager::unload_all() {}
size_t PluginManager::count() const { return 0; }
