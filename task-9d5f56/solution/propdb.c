/* propdb.c - Unicode property database with ICU USet support
 *
 *
 * Parses Unicode property data files and provides fast code-point lookups.
 * Uses ICU's USet API for Extended_Pictographic set membership testing.
 * Compile: gcc -shared -fPIC -O2 $(pkg-config --cflags icu-uc) -o libpropdb.so propdb.c $(pkg-config --libs icu-uc)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unicode/uset.h>
#include <unicode/utypes.h>

#define MAX_CP 0x110000

/* ---- Grapheme_Cluster_Break values ---- */
#define GCB_OTHER          0
#define GCB_CR             1
#define GCB_LF             2
#define GCB_CONTROL        3
#define GCB_EXTEND         4
#define GCB_ZWJ            5
#define GCB_RI             6
#define GCB_PREPEND        7
#define GCB_SPACINGMARK    8
#define GCB_L              9
#define GCB_V              10
#define GCB_T              11
#define GCB_LV             12
#define GCB_LVT            13

/* ---- Word_Break values ---- */
#define WB_OTHER           0
#define WB_CR              1
#define WB_LF              2
#define WB_NEWLINE         3
#define WB_EXTEND          4
#define WB_ZWJ             5
#define WB_RI              6
#define WB_FORMAT          7
#define WB_KATAKANA        8
#define WB_HEBREW_LETTER   9
#define WB_ALETTER         10
#define WB_SINGLE_QUOTE    11
#define WB_DOUBLE_QUOTE    12
#define WB_MIDNUMLET       13
#define WB_MIDLETTER       14
#define WB_MIDNUM          15
#define WB_NUMERIC         16
#define WB_EXTENDNUMLET    17
#define WB_WSEGSPACE       18

/* ---- Sentence_Break values ---- */
#define SB_OTHER           0
#define SB_CR              1
#define SB_LF              2
#define SB_SEP             3
#define SB_EXTEND          4
#define SB_FORMAT          5
#define SB_SP              6
#define SB_LOWER           7
#define SB_UPPER           8
#define SB_OLETTER         9
#define SB_NUMERIC         10
#define SB_ATERM           11
#define SB_STERM           12
#define SB_CLOSE           13
#define SB_SCONTINUE       14

/* ---- Indic_Conjunct_Break values ---- */
#define INCB_NONE          0
#define INCB_CONSONANT     1
#define INCB_EXTEND        2
#define INCB_LINKER        3

/* ---- Static tables ---- */
static uint8_t gcb_table[MAX_CP];
static uint8_t wb_table[MAX_CP];
static uint8_t sb_table[MAX_CP];
static uint8_t incb_table[MAX_CP];
static USet *ext_pict_set = NULL;
static int initialized = 0;

/* ---- Helpers ---- */
static char *trim_str(char *s) {
    while (*s == ' ' || *s == '\t') s++;
    char *e = s + strlen(s) - 1;
    while (e >= s && (*e == ' ' || *e == '\t' || *e == '\n' || *e == '\r'))
        *e-- = '\0';
    return s;
}

/* ---- Property name -> enum mappers ---- */
static int map_gcb(const char *n) {
    if (!strcmp(n, "CR")) return GCB_CR;
    if (!strcmp(n, "LF")) return GCB_LF;
    if (!strcmp(n, "Control")) return GCB_CONTROL;
    if (!strcmp(n, "Extend")) return GCB_EXTEND;
    if (!strcmp(n, "ZWJ")) return GCB_ZWJ;
    if (!strcmp(n, "Regional_Indicator")) return GCB_RI;
    if (!strcmp(n, "Prepend")) return GCB_PREPEND;
    if (!strcmp(n, "SpacingMark")) return GCB_SPACINGMARK;
    if (!strcmp(n, "L")) return GCB_L;
    if (!strcmp(n, "V")) return GCB_V;
    if (!strcmp(n, "T")) return GCB_T;
    if (!strcmp(n, "LV")) return GCB_LV;
    if (!strcmp(n, "LVT")) return GCB_LVT;
    return GCB_OTHER;
}

static int map_wb(const char *n) {
    if (!strcmp(n, "CR")) return WB_CR;
    if (!strcmp(n, "LF")) return WB_LF;
    if (!strcmp(n, "Newline")) return WB_NEWLINE;
    if (!strcmp(n, "Extend")) return WB_EXTEND;
    if (!strcmp(n, "ZWJ")) return WB_ZWJ;
    if (!strcmp(n, "Regional_Indicator")) return WB_RI;
    if (!strcmp(n, "Format")) return WB_FORMAT;
    if (!strcmp(n, "Katakana")) return WB_KATAKANA;
    if (!strcmp(n, "Hebrew_Letter")) return WB_HEBREW_LETTER;
    if (!strcmp(n, "ALetter")) return WB_ALETTER;
    if (!strcmp(n, "Single_Quote")) return WB_SINGLE_QUOTE;
    if (!strcmp(n, "Double_Quote")) return WB_DOUBLE_QUOTE;
    if (!strcmp(n, "MidNumLet")) return WB_MIDNUMLET;
    if (!strcmp(n, "MidLetter")) return WB_MIDLETTER;
    if (!strcmp(n, "MidNum")) return WB_MIDNUM;
    if (!strcmp(n, "Numeric")) return WB_NUMERIC;
    if (!strcmp(n, "ExtendNumLet")) return WB_EXTENDNUMLET;
    if (!strcmp(n, "WSegSpace")) return WB_WSEGSPACE;
    return WB_OTHER;
}

static int map_sb(const char *n) {
    if (!strcmp(n, "CR")) return SB_CR;
    if (!strcmp(n, "LF")) return SB_LF;
    if (!strcmp(n, "Sep")) return SB_SEP;
    if (!strcmp(n, "Extend")) return SB_EXTEND;
    if (!strcmp(n, "Format")) return SB_FORMAT;
    if (!strcmp(n, "Sp")) return SB_SP;
    if (!strcmp(n, "Lower")) return SB_LOWER;
    if (!strcmp(n, "Upper")) return SB_UPPER;
    if (!strcmp(n, "OLetter")) return SB_OLETTER;
    if (!strcmp(n, "Numeric")) return SB_NUMERIC;
    if (!strcmp(n, "ATerm")) return SB_ATERM;
    if (!strcmp(n, "STerm")) return SB_STERM;
    if (!strcmp(n, "Close")) return SB_CLOSE;
    if (!strcmp(n, "SContinue")) return SB_SCONTINUE;
    return SB_OTHER;
}

typedef int (*mapper_fn)(const char *);

/* ---- File parsers ---- */
static void parse_prop_file(const char *path, uint8_t *table, mapper_fn mapper) {
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "propdb: cannot open %s\n", path); return; }
    char line[1024];
    while (fgets(line, sizeof(line), f)) {
        char *h = strchr(line, '#');
        if (h) *h = '\0';
        char *semi = strchr(line, ';');
        if (!semi) continue;
        *semi = '\0';
        char *range_s = trim_str(line);
        char *val_s = trim_str(semi + 1);
        if (!*range_s || !*val_s) continue;
        int val = mapper(val_s);
        uint32_t lo, hi;
        if (sscanf(range_s, "%X..%X", &lo, &hi) == 2) {
            for (uint32_t c = lo; c <= hi && c < (uint32_t)MAX_CP; c++)
                table[c] = (uint8_t)val;
        } else if (sscanf(range_s, "%X", &lo) == 1) {
            if (lo < (uint32_t)MAX_CP) table[lo] = (uint8_t)val;
        }
    }
    fclose(f);
}

static void parse_ext_pict(const char *path) {
    ext_pict_set = uset_openEmpty();
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "propdb: cannot open %s\n", path); return; }
    char line[1024];
    while (fgets(line, sizeof(line), f)) {
        char *h = strchr(line, '#');
        if (h) *h = '\0';
        char *semi = strchr(line, ';');
        if (!semi) continue;
        *semi = '\0';
        char *val = trim_str(semi + 1);
        if (strncmp(val, "Extended_Pictographic", 21) != 0) continue;
        char *range_s = trim_str(line);
        uint32_t lo, hi;
        if (sscanf(range_s, "%X..%X", &lo, &hi) == 2) {
            uset_addRange(ext_pict_set, (UChar32)lo, (UChar32)hi);
        } else if (sscanf(range_s, "%X", &lo) == 1) {
            uset_add(ext_pict_set, (UChar32)lo);
        }
    }
    fclose(f);
    uset_freeze(ext_pict_set);
}

static void parse_incb(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "propdb: cannot open %s (InCB data)\n", path); return; }
    char line[2048];
    while (fgets(line, sizeof(line), f)) {
        char *h = strchr(line, '#');
        if (h) *h = '\0';
        char *s1 = strchr(line, ';');
        if (!s1) continue;
        *s1 = '\0';
        char *s2 = strchr(s1 + 1, ';');
        if (!s2) continue;
        char *prop = trim_str(s1 + 1);
        if (strncmp(prop, "InCB", 4) != 0) continue;
        *s2 = '\0';
        char *val_s = trim_str(s2 + 1);
        int val = INCB_NONE;
        if (!strcmp(val_s, "Consonant")) val = INCB_CONSONANT;
        else if (!strcmp(val_s, "Extend")) val = INCB_EXTEND;
        else if (!strcmp(val_s, "Linker")) val = INCB_LINKER;
        char *range_s = trim_str(line);
        uint32_t lo, hi;
        if (sscanf(range_s, "%X..%X", &lo, &hi) == 2) {
            for (uint32_t c = lo; c <= hi && c < (uint32_t)MAX_CP; c++)
                incb_table[c] = (uint8_t)val;
        } else if (sscanf(range_s, "%X", &lo) == 1) {
            if (lo < (uint32_t)MAX_CP) incb_table[lo] = (uint8_t)val;
        }
    }
    fclose(f);
}

/* ---- Public API ---- */
int init_propdb(const char *data_dir) {
    if (initialized) return 0;
    memset(gcb_table, 0, sizeof(gcb_table));
    memset(wb_table, 0, sizeof(wb_table));
    memset(sb_table, 0, sizeof(sb_table));
    memset(incb_table, 0, sizeof(incb_table));

    char path[512];
    snprintf(path, sizeof(path), "%s/GraphemeBreakProperty.txt", data_dir);
    parse_prop_file(path, gcb_table, map_gcb);
    snprintf(path, sizeof(path), "%s/WordBreakProperty.txt", data_dir);
    parse_prop_file(path, wb_table, map_wb);
    snprintf(path, sizeof(path), "%s/SentenceBreakProperty.txt", data_dir);
    parse_prop_file(path, sb_table, map_sb);
    snprintf(path, sizeof(path), "%s/emoji_data.txt", data_dir);
    parse_ext_pict(path);
    snprintf(path, sizeof(path), "%s/DerivedCoreProperties.txt", data_dir);
    parse_incb(path);

    initialized = 1;
    return 0;
}

int get_gcb(int32_t cp)  { return (cp >= 0 && cp < MAX_CP) ? gcb_table[cp] : 0; }
int get_wb(int32_t cp)   { return (cp >= 0 && cp < MAX_CP) ? wb_table[cp] : 0; }
int get_sb(int32_t cp)   { return (cp >= 0 && cp < MAX_CP) ? sb_table[cp] : 0; }
int get_incb(int32_t cp) { return (cp >= 0 && cp < MAX_CP) ? incb_table[cp] : 0; }

int is_ext_pict(int32_t cp) {
    if (!ext_pict_set) return 0;
    return uset_contains(ext_pict_set, (UChar32)cp) ? 1 : 0;
}
