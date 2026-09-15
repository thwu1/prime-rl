#include "network.h"
#include "engine.h"
#include "crypto.h"

#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>

NetworkLayer::NetworkLayer() : server_fd_(-1), last_error_(ErrorCode::OK) {}

NetworkLayer::~NetworkLayer() {
    if (server_fd_ >= 0) ::close(server_fd_);
}

bool NetworkLayer::bind(int port) {
    server_fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd_ < 0) {
        last_error_ = ErrorCode::CONNECTION_FAILED;
        return false;
    }
    return true;
}

ErrorCode NetworkLayer::last_error() const {
    return last_error_;
}

// Manager integration
static void start_network_manager() {
    auto mgr = NetworkManager::create();
    mgr->run();
}
