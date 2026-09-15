#include "crypto.h"
#include "utils.h"

CryptoHash::CryptoHash(Algorithm algo) : algo_(algo), ctx_(nullptr) {}
CryptoHash::~CryptoHash() {}

void CryptoHash::update(const uint8_t* data, size_t len) {
    // hash update implementation
}

ByteBuffer CryptoHash::finalize() {
    return ByteBuffer();
}

// Convenience wrapper
static ByteBuffer compute_hash(const uint8_t* data, size_t len) {
    CryptoHash hasher(CryptoHash::SHA256);
    hasher.update(data, len, /*finalize=*/true);
    return hasher.finalize();
}
