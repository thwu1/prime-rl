/*
 * kvstore - Simple in-memory key-value store command processor
 *
 * Reads commands from stdin (or a file), one per line.
 * Supported commands:
 *   SET key value          Store a key-value pair
 *   SET key "quoted val"   Store with quoted value (supports \n \t \\ \")
 *   GET key                Retrieve value
 *   DEL key                Delete key
 *   APPEND key value       Append to existing value
 *   RENAME old new         Rename a key
 *   COPY src dst           Copy value to another key
 *   MGET key1 key2 ...     Retrieve multiple values at once
 *   KEYS [pattern]         List keys matching glob (* and ?)
 *   GETRANGE key start end Get substring of value
 *   STRLEN key             Get length of value
 *   EXISTS key             Check if key exists
 *   DUMP                   Dump all key-value pairs
 *   QUIT                   Exit
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define MAX_ENTRIES 1024
#define MAX_LINE    16384
#define PATTERN_BUF 64
#define MGET_BUF    512

typedef struct {
    char *key;
    char *value;
    int active;
} Entry;

static Entry store[MAX_ENTRIES];
static int entry_count = 0;

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

/* Extract next whitespace-delimited word from *pp.
 * Null-terminates the word in place and advances *pp past it.
 * Returns pointer to word, or NULL if nothing left. */
static char *next_word(char **pp) {
    char *p = *pp;
    while (*p && isspace((unsigned char)*p)) p++;
    if (!*p) { *pp = p; return NULL; }
    char *start = p;
    while (*p && !isspace((unsigned char)*p)) p++;
    if (*p) { *p = '\0'; p++; }
    while (*p && isspace((unsigned char)*p)) p++;
    *pp = p;
    return start;
}

/* Return the remaining string from *pp after skipping leading space.
 * Returns NULL if empty. */
static char *rest_of(char **pp) {
    char *p = *pp;
    while (*p && isspace((unsigned char)*p)) p++;
    if (!*p) return NULL;
    *pp = p + strlen(p);
    return p;
}

/* ------------------------------------------------------------------ */
/*  Store operations                                                  */
/* ------------------------------------------------------------------ */

static Entry *find_entry(const char *key) {
    for (int i = 0; i < entry_count; i++) {
        if (store[i].active && strcmp(store[i].key, key) == 0)
            return &store[i];
    }
    return NULL;
}

static Entry *alloc_entry(const char *key) {
    /* reuse inactive slot */
    for (int i = 0; i < entry_count; i++) {
        if (!store[i].active) {
            store[i].key = strdup(key);
            store[i].active = 1;
            return &store[i];
        }
    }
    if (entry_count >= MAX_ENTRIES) return NULL;
    Entry *e = &store[entry_count++];
    e->key = strdup(key);
    e->active = 1;
    return e;
}

/* ------------------------------------------------------------------ */
/*  Value parsing                                                     */
/* ------------------------------------------------------------------ */

/* Parse a double-quoted string, resolving escape sequences.
 * Input s starts and ends with '"'. Returns heap-allocated result. */
static char *parse_quoted(const char *s) {
    int len = strlen(s);
    if (len < 2 || s[0] != '"' || s[len - 1] != '"')
        return strdup(s);

    /* Allocate space for unquoted content.  The content between the two
     * quote characters is at most len-2 bytes; escape sequences only
     * shrink it, so len-2 is a safe upper bound for the result. */
    char *out = malloc(len - 2);
    if (!out) return NULL;

    int j = 0;
    for (int i = 1; i < len - 1; i++) {
        if (s[i] == '\\' && i + 1 < len - 1) {
            switch (s[i + 1]) {
                case 'n':  out[j++] = '\n'; break;
                case 't':  out[j++] = '\t'; break;
                case '\\': out[j++] = '\\'; break;
                case '"':  out[j++] = '"';  break;
                default:   out[j++] = s[i + 1]; break;
            }
            i++;
        } else {
            out[j++] = s[i];
        }
    }
    out[j] = '\0';
    return out;
}

/* Parse a value: quoted strings go through parse_quoted, everything
 * else is taken literally after trimming whitespace. */
static char *parse_value(const char *s) {
    while (*s && isspace((unsigned char)*s)) s++;
    if (*s == '"')
        return parse_quoted(s);
    int len = strlen(s);
    while (len > 0 && isspace((unsigned char)s[len - 1])) len--;
    char *out = malloc(len + 1);
    if (!out) return NULL;
    memcpy(out, s, len);
    out[len] = '\0';
    return out;
}

/* ------------------------------------------------------------------ */
/*  Commands                                                          */
/* ------------------------------------------------------------------ */

static void cmd_set(char *args) {
    char *key = next_word(&args);
    if (!key) { printf("ERROR: SET requires key and value\n"); return; }
    char *val_str = rest_of(&args);
    if (!val_str) { printf("ERROR: SET requires a value\n"); return; }

    Entry *e = find_entry(key);
    if (e) {
        free(e->value);
        e->value = parse_value(val_str);
    } else {
        e = alloc_entry(key);
        if (!e) { printf("ERROR: store full\n"); return; }
        e->value = parse_value(val_str);
    }
    printf("OK\n");
}

static void cmd_get(char *args) {
    char *key = next_word(&args);
    if (!key) { printf("ERROR: GET requires a key\n"); return; }
    Entry *e = find_entry(key);
    if (e)
        printf("%s\n", e->value);
    else
        printf("(nil)\n");
}

static void cmd_del(char *args) {
    char *key = next_word(&args);
    if (!key) { printf("ERROR: DEL requires a key\n"); return; }
    Entry *e = find_entry(key);
    if (e) {
        free(e->key);
        free(e->value);
        e->key = NULL;
        e->value = NULL;
        e->active = 0;
        printf("(1)\n");
    } else {
        printf("(0)\n");
    }
}

static void cmd_append(char *args) {
    char *key = next_word(&args);
    if (!key) { printf("ERROR: APPEND requires key and value\n"); return; }
    char *val = rest_of(&args);
    if (!val) { printf("ERROR: APPEND requires a value\n"); return; }

    Entry *e = find_entry(key);
    if (!e) {
        e = alloc_entry(key);
        if (!e) { printf("ERROR: store full\n"); return; }
        e->value = strdup(val);
    } else {
        size_t old_len = strlen(e->value);
        size_t add_len = strlen(val);
        char *new_val = realloc(e->value, old_len + add_len + 1);
        if (!new_val) { printf("ERROR: out of memory\n"); return; }
        memcpy(new_val + old_len, val, add_len + 1);
        e->value = new_val;
    }
    printf("OK\n");
}

static void cmd_rename(char *args) {
    char *old_key = next_word(&args);
    char *new_key = next_word(&args);
    if (!old_key || !new_key) {
        printf("ERROR: RENAME requires old and new key\n");
        return;
    }

    Entry *old_e = find_entry(old_key);
    if (!old_e) { printf("ERROR: key not found\n"); return; }

    /* Remove destination if it already exists */
    Entry *existing = find_entry(new_key);
    if (existing) {
        free(existing->key);
        free(existing->value);
        existing->key = NULL;
        existing->value = NULL;
        existing->active = 0;
    }

    /* Create new entry and transfer the value */
    Entry *new_e = alloc_entry(new_key);
    if (!new_e) { printf("ERROR: store full\n"); return; }
    new_e->value = old_e->value;

    /* Clean up old entry */
    free(old_e->key);
    free(old_e->value);
    old_e->key = NULL;
    old_e->value = NULL;
    old_e->active = 0;

    printf("OK\n");
}

static void cmd_copy(char *args) {
    char *src_key = next_word(&args);
    char *dst_key = next_word(&args);
    if (!src_key || !dst_key) {
        printf("ERROR: COPY requires src and dst keys\n");
        return;
    }

    Entry *src_e = find_entry(src_key);
    if (!src_e) { printf("ERROR: source key not found\n"); return; }

    Entry *dst_e = find_entry(dst_key);
    if (dst_e) {
        free(dst_e->value);
        dst_e->value = strdup(src_e->value);
    } else {
        dst_e = alloc_entry(dst_key);
        if (!dst_e) { printf("ERROR: store full\n"); return; }
        dst_e->value = strdup(src_e->value);
    }
    printf("OK\n");
}

/* Simple glob matching: * matches any sequence, ? matches one char */
static int glob_match(const char *pattern, const char *str) {
    while (*pattern && *str) {
        if (*pattern == '*') {
            pattern++;
            if (!*pattern) return 1;
            while (*str) {
                if (glob_match(pattern, str)) return 1;
                str++;
            }
            return 0;
        }
        if (*pattern == '?') {
            pattern++;
            str++;
            continue;
        }
        if (*pattern != *str) return 0;
        pattern++;
        str++;
    }
    while (*pattern == '*') pattern++;
    return (!*pattern && !*str);
}

static void cmd_keys(char *args) {
    char *pattern = next_word(&args);
    char normalized[PATTERN_BUF];

    if (pattern) {
        /* Normalise pattern to lowercase for case-insensitive matching */
        int i;
        for (i = 0; pattern[i]; i++) {
            normalized[i] = tolower((unsigned char)pattern[i]);
        }
        normalized[i] = '\0';
    }

    int count = 0;
    for (int i = 0; i < entry_count; i++) {
        if (!store[i].active) continue;
        if (pattern) {
            char key_lower[256];
            int k;
            for (k = 0; store[i].key[k] && k < 255; k++)
                key_lower[k] = tolower((unsigned char)store[i].key[k]);
            key_lower[k] = '\0';
            if (!glob_match(normalized, key_lower)) continue;
        }
        printf("%d) %s\n", ++count, store[i].key);
    }
    if (count == 0) printf("(empty)\n");
}

static void cmd_getrange(char *args) {
    char *key = next_word(&args);
    char *start_s = next_word(&args);
    char *end_s = next_word(&args);
    if (!key || !start_s || !end_s) {
        printf("ERROR: GETRANGE requires key, start, end\n");
        return;
    }

    Entry *e = find_entry(key);
    if (!e) { printf("(nil)\n"); return; }

    int len = (int)strlen(e->value);
    int start = atoi(start_s);
    int end = atoi(end_s);

    /* Handle negative indices (count from end) */
    if (start < 0) start = len + start;
    if (start < 0) start = 0;
    if (start >= len) { printf("\"\"\n"); return; }

    if (end < 0) end = len + end;
    if (end < start) { printf("\"\"\n"); return; }

    int n = end - start + 1;
    char *buf = malloc(n + 1);
    if (!buf) { printf("ERROR: out of memory\n"); return; }
    memcpy(buf, e->value + start, n);
    buf[n] = '\0';
    printf("\"%s\"\n", buf);
    free(buf);
}

static void cmd_mget(char *args) {
    char *keys[128];
    int nkeys = 0;
    char *key;
    while ((key = next_word(&args)) != NULL && nkeys < 128) {
        keys[nkeys++] = key;
    }
    if (nkeys == 0) { printf("ERROR: MGET requires at least one key\n"); return; }

    /* Format all values into a response buffer */
    char response[MGET_BUF];
    int pos = 0;
    for (int i = 0; i < nkeys; i++) {
        Entry *e = find_entry(keys[i]);
        if (e) {
            pos += sprintf(response + pos, "%d) %s\n", i + 1, e->value);
        } else {
            pos += sprintf(response + pos, "%d) (nil)\n", i + 1);
        }
    }
    printf("%s", response);
}

static void cmd_strlen(char *args) {
    char *key = next_word(&args);
    if (!key) { printf("ERROR: STRLEN requires a key\n"); return; }
    Entry *e = find_entry(key);
    if (e)
        printf("(%d)\n", (int)strlen(e->value));
    else
        printf("(nil)\n");
}

static void cmd_exists(char *args) {
    char *key = next_word(&args);
    if (!key) { printf("ERROR: EXISTS requires a key\n"); return; }
    printf("(%d)\n", find_entry(key) ? 1 : 0);
}

static void cmd_dump(void) {
    int count = 0;
    for (int i = 0; i < entry_count; i++) {
        if (!store[i].active) continue;
        printf("%s = %s\n", store[i].key, store[i].value);
        count++;
    }
    if (count == 0) printf("(empty)\n");
}

/* ------------------------------------------------------------------ */
/*  Main loop                                                         */
/* ------------------------------------------------------------------ */

static void process_line(char *line) {
    /* Strip trailing newline / carriage-return */
    size_t len = strlen(line);
    while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r'))
        line[--len] = '\0';

    /* Skip leading whitespace */
    char *p = line;
    while (*p && isspace((unsigned char)*p)) p++;
    if (!*p || *p == '#') return;   /* empty or comment */

    /* Extract command word and upper-case it */
    char *cmd_start = p;
    while (*p && !isspace((unsigned char)*p)) p++;
    if (*p) { *p = '\0'; p++; }
    for (char *c = cmd_start; *c; c++) *c = toupper((unsigned char)*c);

    /* Skip whitespace before arguments */
    while (*p && isspace((unsigned char)*p)) p++;

    /* Dispatch */
    if      (strcmp(cmd_start, "SET") == 0)      cmd_set(p);
    else if (strcmp(cmd_start, "GET") == 0)      cmd_get(p);
    else if (strcmp(cmd_start, "DEL") == 0)      cmd_del(p);
    else if (strcmp(cmd_start, "APPEND") == 0)   cmd_append(p);
    else if (strcmp(cmd_start, "RENAME") == 0)   cmd_rename(p);
    else if (strcmp(cmd_start, "COPY") == 0)     cmd_copy(p);
    else if (strcmp(cmd_start, "MGET") == 0)     cmd_mget(p);
    else if (strcmp(cmd_start, "KEYS") == 0)     cmd_keys(p);
    else if (strcmp(cmd_start, "GETRANGE") == 0) cmd_getrange(p);
    else if (strcmp(cmd_start, "STRLEN") == 0)   cmd_strlen(p);
    else if (strcmp(cmd_start, "EXISTS") == 0)   cmd_exists(p);
    else if (strcmp(cmd_start, "DUMP") == 0)     cmd_dump();
    else if (strcmp(cmd_start, "QUIT") == 0)     exit(0);
    else printf("ERROR: unknown command '%s'\n", cmd_start);
}

int main(int argc, char *argv[]) {
    char line[MAX_LINE];
    FILE *input = stdin;

    if (argc > 1) {
        input = fopen(argv[1], "r");
        if (!input) {
            fprintf(stderr, "Cannot open %s\n", argv[1]);
            return 1;
        }
    }

    while (fgets(line, sizeof(line), input)) {
        process_line(line);
    }

    if (input != stdin) fclose(input);
    return 0;
}
