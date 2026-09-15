#ifndef NETWORK_H
#define NETWORK_H

#include "types.h"

class NetworkLayer {
public:
    NetworkLayer();
    ~NetworkLayer();

    bool bind(int port);
    bool listen(int backlog);
    ConnectionId accept();

    ssize_t send(ConnectionId id, const ByteBuffer& data);
    ssize_t recv(ConnectionId id, ByteBuffer& buffer, size_t max_len);

    void close(ConnectionId id);

    ErrorCode last_error() const;

private:
    int server_fd_;
    ErrorCode last_error_;
};

#endif // NETWORK_H
