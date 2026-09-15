
#ifndef PARSER_H
#define PARSER_H

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ======================================================================
   Parse state — a bounded view into a byte buffer
   ====================================================================== */
typedef struct {
    const uint8_t *data;
    size_t pos;
    size_t len;   /* one-past-end bound (may be < total buffer for sub-streams) */
} pstate_t;

/* ======================================================================
   JSON value representation
   ====================================================================== */
typedef enum { JV_NULL, JV_INT, JV_ARRAY, JV_OBJECT } jv_type_t;

typedef struct jv jv_t;

typedef struct {
    char  *key;
    jv_t  *val;
} jv_kv_t;

struct jv {
    jv_type_t type;
    union {
        int64_t ival;
        struct { jv_t **items; size_t len; size_t cap; } arr;
        struct { jv_kv_t *kvs; size_t len; size_t cap; } obj;
    };
};

/* ======================================================================
   Parse-state operations
   ====================================================================== */
void    ps_init(pstate_t *ps, const uint8_t *data, size_t len);
int     ps_read_u8(pstate_t *ps, uint8_t *out);
int     ps_read_be16(pstate_t *ps, uint16_t *out);
int     ps_read_be32(pstate_t *ps, uint32_t *out);
int     ps_read_le16(pstate_t *ps, uint16_t *out);
int     ps_read_le32(pstate_t *ps, uint32_t *out);
int     ps_match(pstate_t *ps, const uint8_t *bytes, size_t n);
int     ps_at_end(pstate_t *ps);
size_t  ps_save(pstate_t *ps);
void    ps_restore(pstate_t *ps, size_t saved);
int     ps_chunk(pstate_t *ps, size_t n, pstate_t *sub);

/* ======================================================================
   JSON value construction / inspection
   ====================================================================== */
jv_t   *jv_null(void);
jv_t   *jv_int(int64_t v);
jv_t   *jv_array(void);
void    jv_push(jv_t *arr, jv_t *item);
jv_t   *jv_object(void);
void    jv_set(jv_t *obj, const char *key, jv_t *val);
int64_t jv_as_int(jv_t *v);
void    jv_print(jv_t *v, FILE *fp);
void    jv_free(jv_t *v);

/* ======================================================================
   File I/O helper
   ====================================================================== */
uint8_t *read_file(const char *path, size_t *out_len);

#endif /* PARSER_H */
