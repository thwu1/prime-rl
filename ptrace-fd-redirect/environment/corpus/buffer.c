#include <stdlib.h>
#include <string.h>

typedef struct {
    char *data;
    size_t len;
    size_t cap;
} Buffer;

Buffer *buffer_new(size_t initial_cap) {
    Buffer *buf = malloc(sizeof(Buffer));
    if (!buf) return NULL;
    buf->data = malloc(initial_cap);
    if (!buf->data) { free(buf); return NULL; }
    buf->len = 0;
    buf->cap = initial_cap;
    return buf;
}

int buffer_append(Buffer *buf, const char *data, size_t len) {
    if (buf->len + len > buf->cap) {
        size_t new_cap = buf->cap * 2;
        while (new_cap < buf->len + len)
            new_cap *= 2;
        char *new_data = realloc(buf->data, new_cap);
        if (!new_data) return -1;
        buf->data = new_data;
        buf->cap = new_cap;
    }
    memcpy(buf->data + buf->len, data, len);
    buf->len += len;
    return 0;
}

void buffer_free(Buffer *buf) {
    if (buf) {
        free(buf->data);
        free(buf);
    }
}

char *buffer_to_string(Buffer *buf) {
    char *result = malloc(buf->len + 1);
    if (!result) return NULL;
    memcpy(result, buf->data, buf->len);
    result[buf->len] = '\0';
    return result;
}
