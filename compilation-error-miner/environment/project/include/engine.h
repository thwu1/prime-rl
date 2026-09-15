#ifndef ENGINE_H
#define ENGINE_H

#include "config.h"
#include "types.h"

#define ENGINE_CAST(ptr) static_cast<int*>(ptr)

class Engine {
public:
    Engine();
    ~Engine();

    bool initialize(const GlobalConfig& config);
    void shutdown();

    ErrorCode process(const ByteBuffer& input, ByteBuffer& output);
    void clear_buffer();

    ConnectionId connect(const std::string& host, int port);
    void disconnect(ConnectionId id);

    size_t buffer_size() const;
    bool is_running() const;

private:
    struct Impl;
    Impl* pImpl;
};

#endif // ENGINE_H
