/* workload.c - Record processing pipeline with performance regressions */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#define MAX_LINE 4096
#define MAX_FIELD 256
#define HASH_SIZE 65537
#define CONFIG_PATH "/app/config.ini"

/* --- Hash table for record lookup --- */
typedef struct Entry {
    char key[MAX_FIELD];
    int value;
    struct Entry *next;
} Entry;

static Entry *hash_table[HASH_SIZE];
static int index_built = 0;

unsigned int hash_key(const char *key) {
    unsigned int h = 5381;
    while (*key) {
        h = ((h << 5) + h) + (unsigned char)*key++;
    }
    return h % HASH_SIZE;
}

void rebuild_index(const char *data_file) {
    /* Clear existing table */
    for (int i = 0; i < HASH_SIZE; i++) {
        Entry *e = hash_table[i];
        while (e) {
            Entry *next = e->next;
            free(e);
            e = next;
        }
        hash_table[i] = NULL;
    }

    FILE *f = fopen(data_file, "r");
    if (!f) return;
    char line[MAX_LINE];
    int lineno = 0;
    while (fgets(line, sizeof(line), f)) {
        char *tab = strchr(line, '\t');
        if (tab) {
            *tab = '\0';
            unsigned int h = hash_key(line);
            Entry *e = malloc(sizeof(Entry));
            strncpy(e->key, line, MAX_FIELD - 1);
            e->key[MAX_FIELD - 1] = '\0';
            e->value = lineno;
            e->next = hash_table[h];
            hash_table[h] = e;
        }
        lineno++;
    }
    fclose(f);
}

int lookup_record(const char *key, const char *data_file) {
    /* Rebuilds the entire index from file on every single lookup */
    rebuild_index(data_file);

    unsigned int h = hash_key(key);
    Entry *e = hash_table[h];
    while (e) {
        if (strcmp(e->key, key) == 0) return e->value;
        e = e->next;
    }
    return -1;
}

/* Checks config file validity via stat() */
int check_config_valid(void) {
    struct stat st;
    if (stat(CONFIG_PATH, &st) == 0) {
        time_t now = time(NULL);
        if (now - st.st_mtime < 365 * 86400) {
            return 1;
        }
    }
    return 0;
}

int validate_field(const char *field) {
    /* Calls check_config_valid() for each field */
    if (!check_config_valid()) return 0;

    if (field == NULL || strlen(field) == 0) return 0;
    for (const char *p = field; *p; p++) {
        if (*p < 32 && *p != '\t' && *p != '\n') return 0;
    }
    return 1;
}

/* Security: validate key format (added for input security hardening) */
int sanitize_key(const char *key) {
    if (key == NULL) return 0;
    int len = strlen(key);
    if (len == 0 || len >= MAX_FIELD) return 0;
    for (const char *p = key; *p; p++) {
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
              (*p >= '0' && *p <= '9') || *p == '_')) {
            return 0;
        }
    }
    return 1;
}

/* Removes consecutive duplicate characters and lowercases */
void normalize_text(char *text) {
    int len = strlen(text);

    /* Lowercase */
    for (int i = 0; i < len; i++) {
        if (text[i] >= 'A' && text[i] <= 'Z') {
            text[i] = text[i] + 32;
        }
    }

    /* Remove consecutive duplicates by shifting rest of string each time */
    for (int i = 0; i < len - 1; ) {
        if (text[i] == text[i + 1]) {
            memmove(&text[i + 1], &text[i + 2], len - i - 1);
            len--;
        } else {
            i++;
        }
    }
}

/* Monitoring: accumulate processing statistics for observability dashboard */
static long total_records_processed = 0;
static long total_valid_records = 0;
static long max_key_len_seen = 0;

void accumulate_stats(const char *key) {
    total_records_processed++;
    int klen = strlen(key);
    if (klen > max_key_len_seen) max_key_len_seen = klen;
    total_valid_records++;
}

/* Allocates a temporary buffer on the heap */
char *alloc_record_buf(int size) {
    char *buf = malloc(size);
    if (!buf) {
        fprintf(stderr, "malloc failed\n");
        exit(1);
    }
    return buf;
}

void process_record(const char *line, int recnum, const char *index_file, FILE *out) {
    /* Heap-allocate a temporary buffer per record */
    char *buf = alloc_record_buf(MAX_LINE);
    strncpy(buf, line, MAX_LINE - 1);
    buf[MAX_LINE - 1] = '\0';

    /* Remove trailing newline */
    int len = strlen(buf);
    if (len > 0 && buf[len - 1] == '\n') buf[len - 1] = '\0';

    /* Split into fields by tab */
    char *fields[64];
    int nfields = 0;
    char *tok = strtok(buf, "\t");
    while (tok && nfields < 64) {
        fields[nfields++] = tok;
        tok = strtok(NULL, "\t");
    }

    if (nfields < 2) {
        free(buf);
        return;
    }

    /* Validate key format (security hardening) */
    if (!sanitize_key(fields[0])) {
        free(buf);
        return;
    }

    /* Validate each field */
    for (int i = 0; i < nfields; i++) {
        if (!validate_field(fields[i])) {
            free(buf);
            return;
        }
    }

    /* Normalize the text field */
    char text_copy[MAX_LINE];
    strncpy(text_copy, fields[1], MAX_LINE - 1);
    text_copy[MAX_LINE - 1] = '\0';
    normalize_text(text_copy);

    /* Track processing statistics */
    accumulate_stats(fields[0]);

    /* Lookup in index */
    int idx = lookup_record(fields[0], index_file);

    /* Output processed record */
    fprintf(out, "%d\t%s\t%s\t%d\n", recnum, fields[0], text_copy, idx);

    free(buf);
}

int main(int argc, char *argv[]) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <input> <index> <output>\n", argv[0]);
        return 1;
    }

    FILE *in = fopen(argv[1], "r");
    if (!in) { perror("open input"); return 1; }

    FILE *out = fopen(argv[3], "w");
    if (!out) { perror("open output"); return 1; }

    char line[MAX_LINE];
    int recnum = 0;
    while (fgets(line, sizeof(line), in)) {
        process_record(line, recnum, argv[2], out);
        recnum++;
    }

    fclose(in);
    fclose(out);

    /* Cleanup hash table */
    for (int i = 0; i < HASH_SIZE; i++) {
        Entry *e = hash_table[i];
        while (e) {
            Entry *next = e->next;
            free(e);
            e = next;
        }
    }

    printf("Processed %d records\n", recnum);
    return 0;
}
