unsigned int jenkins_hash(const char *key, int len) {
    unsigned int hash = 0;
    for (int i = 0; i < len; i++) {
        hash += key[i];
        hash += (hash << 10);
        hash ^= (hash >> 6);
    }
    hash += (hash << 3);
    hash ^= (hash >> 11);
    hash += (hash << 15);
    return hash;
}

int main(void) {
    const char *keys[] = {"hello", "world", "compiler", "optimization", "benchmark"};
    unsigned int total = 0;
    for (int i = 0; i < 5; i++) {
        int len = 0;
        const char *k = keys[i];
        while (k[len])
            len++;
        total ^= jenkins_hash(k, len);
    }
    return total & 0xFF;
}
