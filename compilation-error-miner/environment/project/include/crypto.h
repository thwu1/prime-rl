#ifndef CRYPTO_H
#define CRYPTO_H

#include "types.h"
#include "config.h"

class CryptoHash {
public:
    enum Algorithm { SHA256, SHA512, BLAKE2 };

    explicit CryptoHash(Algorithm algo = SHA256);
    ~CryptoHash();

    void update(const uint8_t* data, size_t len);
    ByteBuffer finalize();

    static ByteBuffer hash(Algorithm algo, const ByteBuffer& data);

private:
    Algorithm algo_;
    void* ctx_;
};

class CryptoAES {
public:
    static ByteBuffer encrypt(const ByteBuffer& key, const ByteBuffer& iv,
                              const ByteBuffer& plaintext);
    static ByteBuffer decrypt(const ByteBuffer& key, const ByteBuffer& iv,
                              const ByteBuffer& ciphertext);
};

#endif // CRYPTO_H
