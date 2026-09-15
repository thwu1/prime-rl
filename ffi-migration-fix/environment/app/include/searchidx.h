#ifndef SEARCHIDX_H
#define SEARCHIDX_H

#include <stdint.h>

/* Token produced by the tokenizer */
typedef struct {
    char text[128];
    uint32_t position;
} SearchIdxToken;

/* Search result from the index */
typedef struct {
    uint32_t doc_id;
    float score;
} SearchResult;

/* Tokenizer API (implemented in Rust) */
SearchIdxToken* searchidx_tokenize(const char* input, uint32_t* token_count);
void searchidx_free_tokens(SearchIdxToken* tokens, uint32_t count);

/* Index API (implemented in C) */
uint32_t searchidx_index_document(const char* text);
SearchResult* searchidx_search(const char* query, uint32_t* result_count);
void searchidx_free_results(SearchResult* results);
void searchidx_reset_index(void);

#endif /* SEARCHIDX_H */
