#ifndef PLUGIN_H
#define PLUGIN_H

#include "engine.h"

class Plugin {
public:
    virtual ~Plugin() = default;

    virtual const char* name() const = 0;
    virtual bool initialize(Engine& engine) = 0;
    virtual void shutdown() = 0;

    virtual ErrorCode on_data(const ByteBuffer& data) = 0;
};

class PluginManager {
public:
    explicit PluginManager(Engine& engine);

    bool load(const std::string& path);
    void unload_all();

    size_t count() const;

private:
    Engine& engine_;
};

#endif // PLUGIN_H
