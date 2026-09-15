#include "searchidx.h"
#include <stdlib.h>
#include <string.h>

#define MAX_POSTING_LISTS 4096
#define MAX_DOCS_PER_POSTING 256

typedef struct {
    char token[128];
    uint32_t doc_ids[MAX_DOCS_PER_POSTING];
    float scores[MAX_DOCS_PER_POSTING];
    uint32_t count;
} PostingList;

static PostingList g_postings[MAX_POSTING_LISTS];
static uint32_t g_posting_count = 0;
static uint32_t g_next_doc_id = 1;

static PostingList* find_or_create_posting(const char* token) {
    uint32_t i;
    for (i = 0; i < g_posting_count; i++) {
        if (strcmp(g_postings[i].token, token) == 0) {
            return &g_postings[i];
        }
    }
    if (g_posting_count >= MAX_POSTING_LISTS) {
        return NULL;
    }
    PostingList* pl = &g_postings[g_posting_count++];
    memset(pl, 0, sizeof(PostingList));
    strncpy(pl->token, token, 127);
    pl->token[127] = '\0';
    return pl;
}

uint32_t searchidx_index_document(const char* text) {
    uint32_t i, j;
    if (!text) return 0;

    uint32_t doc_id = g_next_doc_id++;
    uint32_t token_count = 0;
    SearchIdxToken* tokens = searchidx_tokenize(text, &token_count);

    if (!tokens || token_count == 0) {
        if (tokens) searchidx_free_tokens(tokens, token_count);
        return doc_id;
    }

    for (i = 0; i < token_count; i++) {
        PostingList* pl = find_or_create_posting(tokens[i].text);
        if (!pl) continue;

        /* Check if doc already in this posting list */
        int found = 0;
        for (j = 0; j < pl->count; j++) {
            if (pl->doc_ids[j] == doc_id) {
                pl->scores[j] += 1.0f;
                found = 1;
                break;
            }
        }
        if (!found && pl->count < MAX_DOCS_PER_POSTING) {
            pl->doc_ids[pl->count] = doc_id;
            pl->scores[pl->count] = 1.0f;
            pl->count++;
        }
    }

    searchidx_free_tokens(tokens, token_count);
    return doc_id;
}

SearchResult* searchidx_search(const char* query, uint32_t* result_count) {
    uint32_t q, i, j, r;
    *result_count = 0;
    if (!query) return NULL;

    uint32_t query_token_count = 0;
    SearchIdxToken* query_tokens = searchidx_tokenize(query, &query_token_count);

    if (!query_tokens || query_token_count == 0) {
        if (query_tokens) searchidx_free_tokens(query_tokens, query_token_count);
        return NULL;
    }

    uint32_t max_results = 1024;
    SearchResult* results = (SearchResult*)malloc(max_results * sizeof(SearchResult));
    uint32_t count = 0;

    for (q = 0; q < query_token_count; q++) {
        for (i = 0; i < g_posting_count; i++) {
            if (strcmp(g_postings[i].token, query_tokens[q].text) != 0) continue;

            for (j = 0; j < g_postings[i].count; j++) {
                int found = 0;
                for (r = 0; r < count; r++) {
                    if (results[r].doc_id == g_postings[i].doc_ids[j]) {
                        results[r].score += g_postings[i].scores[j];
                        found = 1;
                        break;
                    }
                }
                if (!found && count < max_results) {
                    results[count].doc_id = g_postings[i].doc_ids[j];
                    results[count].score = g_postings[i].scores[j];
                    count++;
                }
            }
        }
    }

    searchidx_free_tokens(query_tokens, query_token_count);
    *result_count = count;

    if (count == 0) {
        free(results);
        return NULL;
    }

    return results;
}

void searchidx_free_results(SearchResult* results) {
    free(results);
}

void searchidx_reset_index(void) {
    g_posting_count = 0;
    g_next_doc_id = 1;
    memset(g_postings, 0, sizeof(g_postings));
}
