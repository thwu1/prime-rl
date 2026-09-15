
#include "parser.h"

/* ======================================================================
   Parse-state operations
   ====================================================================== */

void ps_init(pstate_t *ps, const uint8_t *data, size_t len) {
    ps->data = data;
    ps->pos  = 0;
    ps->len  = len;
}

int ps_read_u8(pstate_t *ps, uint8_t *out) {
    if (ps->pos >= ps->len) return 0;
    *out = ps->data[ps->pos++];
    return 1;
}

int ps_read_be16(pstate_t *ps, uint16_t *out) {
    if (ps->pos + 2 > ps->len) return 0;
    *out = ((uint16_t)ps->data[ps->pos] << 8) | ps->data[ps->pos + 1];
    ps->pos += 2;
    return 1;
}

int ps_read_be32(pstate_t *ps, uint32_t *out) {
    if (ps->pos + 4 > ps->len) return 0;
    *out = ((uint32_t)ps->data[ps->pos] << 24) |
           ((uint32_t)ps->data[ps->pos + 1] << 16) |
           ((uint32_t)ps->data[ps->pos + 2] << 8) |
           ps->data[ps->pos + 3];
    ps->pos += 4;
    return 1;
}

int ps_read_le16(pstate_t *ps, uint16_t *out) {
    if (ps->pos + 2 > ps->len) return 0;
    *out = ps->data[ps->pos] | ((uint16_t)ps->data[ps->pos + 1] << 8);
    ps->pos += 2;
    return 1;
}

int ps_read_le32(pstate_t *ps, uint32_t *out) {
    if (ps->pos + 4 > ps->len) return 0;
    *out = ps->data[ps->pos] |
           ((uint32_t)ps->data[ps->pos + 1] << 8) |
           ((uint32_t)ps->data[ps->pos + 2] << 16) |
           ((uint32_t)ps->data[ps->pos + 3] << 24);
    ps->pos += 4;
    return 1;
}

int ps_match(pstate_t *ps, const uint8_t *bytes, size_t n) {
    if (ps->pos + n > ps->len) return 0;
    if (memcmp(ps->data + ps->pos, bytes, n) != 0) return 0;
    ps->pos += n;
    return 1;
}

int ps_at_end(pstate_t *ps) {
    return ps->pos >= ps->len;
}

size_t ps_save(pstate_t *ps) {
    return ps->pos;
}

void ps_restore(pstate_t *ps, size_t saved) {
    ps->pos = saved;
}

int ps_chunk(pstate_t *ps, size_t n, pstate_t *sub) {
    if (ps->pos + n > ps->len) return 0;
    sub->data = ps->data;
    sub->pos  = ps->pos;
    sub->len  = ps->pos + n;
    ps->pos  += n;
    return 1;
}

/* ======================================================================
   JSON value construction
   ====================================================================== */

jv_t *jv_null(void) {
    jv_t *v = (jv_t *)calloc(1, sizeof(jv_t));
    v->type = JV_NULL;
    return v;
}

jv_t *jv_int(int64_t val) {
    jv_t *v = (jv_t *)calloc(1, sizeof(jv_t));
    v->type = JV_INT;
    v->ival = val;
    return v;
}

jv_t *jv_array(void) {
    jv_t *v = (jv_t *)calloc(1, sizeof(jv_t));
    v->type    = JV_ARRAY;
    v->arr.cap = 8;
    v->arr.len = 0;
    v->arr.items = (jv_t **)calloc(v->arr.cap, sizeof(jv_t *));
    return v;
}

void jv_push(jv_t *arr, jv_t *item) {
    if (arr->arr.len >= arr->arr.cap) {
        arr->arr.cap *= 2;
        arr->arr.items = (jv_t **)realloc(arr->arr.items,
                                          arr->arr.cap * sizeof(jv_t *));
    }
    arr->arr.items[arr->arr.len++] = item;
}

jv_t *jv_object(void) {
    jv_t *v = (jv_t *)calloc(1, sizeof(jv_t));
    v->type    = JV_OBJECT;
    v->obj.cap = 8;
    v->obj.len = 0;
    v->obj.kvs = (jv_kv_t *)calloc(v->obj.cap, sizeof(jv_kv_t));
    return v;
}

void jv_set(jv_t *obj, const char *key, jv_t *val) {
    if (obj->obj.len >= obj->obj.cap) {
        obj->obj.cap *= 2;
        obj->obj.kvs = (jv_kv_t *)realloc(obj->obj.kvs,
                                           obj->obj.cap * sizeof(jv_kv_t));
    }
    jv_kv_t *e = &obj->obj.kvs[obj->obj.len++];
    e->key = strdup(key);
    e->val = val;
}

int64_t jv_as_int(jv_t *v) {
    if (!v || v->type != JV_INT) return 0;
    return v->ival;
}

/* ======================================================================
   JSON printing  (compact, single-line)
   ====================================================================== */

void jv_print(jv_t *v, FILE *fp) {
    if (!v) { fprintf(fp, "null"); return; }
    switch (v->type) {
    case JV_NULL:
        fprintf(fp, "null");
        break;
    case JV_INT:
        fprintf(fp, "%lld", (long long)v->ival);
        break;
    case JV_ARRAY:
        fputc('[', fp);
        for (size_t i = 0; i < v->arr.len; i++) {
            if (i) fprintf(fp, ", ");
            jv_print(v->arr.items[i], fp);
        }
        fputc(']', fp);
        break;
    case JV_OBJECT:
        fputc('{', fp);
        for (size_t i = 0; i < v->obj.len; i++) {
            if (i) fprintf(fp, ", ");
            fprintf(fp, "\"%s\": ", v->obj.kvs[i].key);
            jv_print(v->obj.kvs[i].val, fp);
        }
        fputc('}', fp);
        break;
    }
}

/* ======================================================================
   JSON deallocation  (recursive)
   ====================================================================== */

void jv_free(jv_t *v) {
    if (!v) return;
    switch (v->type) {
    case JV_ARRAY:
        for (size_t i = 0; i < v->arr.len; i++)
            jv_free(v->arr.items[i]);
        free(v->arr.items);
        break;
    case JV_OBJECT:
        for (size_t i = 0; i < v->obj.len; i++) {
            free(v->obj.kvs[i].key);
            jv_free(v->obj.kvs[i].val);
        }
        free(v->obj.kvs);
        break;
    default:
        break;
    }
    free(v);
}

/* ======================================================================
   File I/O
   ====================================================================== */

uint8_t *read_file(const char *path, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    if (sz < 0) { fclose(f); return NULL; }
    fseek(f, 0, SEEK_SET);
    uint8_t *buf = (uint8_t *)malloc((size_t)sz);
    if (!buf) { fclose(f); return NULL; }
    size_t rd = fread(buf, 1, (size_t)sz, f);
    fclose(f);
    *out_len = rd;
    return buf;
}
