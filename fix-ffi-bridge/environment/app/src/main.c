#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <pthread.h>
#include "sortedset.h"

/* Callback: collect member=score pairs into a buffer */
struct collect_state {
    char buf[4096];
    int pos;
    int count;
};

int collect_cb(const char* member, double score, void* user_data) {
    struct collect_state* state = (struct collect_state*)user_data;
    state->pos += snprintf(state->buf + state->pos,
                           sizeof(state->buf) - (size_t)state->pos,
                           "%s=%.1f ", member, score);
    state->count++;
    return 0;  /* continue */
}

/* Callback: stop after visiting 2 entries */
int stop_after_two(const char* member, double score, void* user_data) {
    int* count = (int*)user_data;
    (*count)++;
    (void)member;
    (void)score;
    return (*count >= 2) ? 1 : 0;
}

/* Thread worker for concurrent access test */
struct thread_arg {
    SortedSet* zs;
    int id;
};

void* writer_thread(void* arg) {
    struct thread_arg* ta = (struct thread_arg*)arg;
    char name[64];
    for (int i = 0; i < 50; i++) {
        snprintf(name, sizeof(name), "t%d_%d", ta->id, i);
        zset_add(ta->zs, name, (double)(ta->id * 1000 + i));
    }
    return NULL;
}

int main(void) {
    printf("=== Sorted Set FFI Demo ===\n\n");

    /* --- Basic operations --- */
    SortedSet* zs = zset_new();
    assert(zs != NULL);

    assert(zset_add(zs, "alice", 10.0) == 1);
    assert(zset_add(zs, "bob", 20.0) == 1);
    assert(zset_add(zs, "charlie", 15.0) == 1);
    assert(zset_add(zs, "dave", 25.0) == 1);
    assert(zset_add(zs, "eve", 5.0) == 1);
    assert(zset_card(zs) == 5);
    printf("Basic add/card: OK\n");

    /* Update existing */
    assert(zset_add(zs, "alice", 12.0) == 0);
    double score;
    assert(zset_score(zs, "alice", &score) == 1);
    assert(score == 12.0);
    printf("Update score: OK\n");

    /* Rank */
    size_t rank;
    assert(zset_rank(zs, "eve", &rank) == 1 && rank == 0);
    assert(zset_rank(zs, "dave", &rank) == 1 && rank == 4);
    printf("Rank: OK\n");

    /* Range by score */
    ZRangeResult* result = zset_range_by_score(zs, 10.0, 20.0);
    assert(result && result->count == 3);
    assert(strcmp(result->members[0], "alice") == 0);
    assert(result->scores[0] == 12.0);
    zset_range_free(result);
    printf("Range by score: OK\n");

    /* Range by rank */
    result = zset_range_by_rank(zs, 1, 3);
    assert(result && result->count == 3);
    assert(strcmp(result->members[0], "alice") == 0);
    zset_range_free(result);
    printf("Range by rank: OK\n");

    /* --- Foreach --- */
    struct collect_state state = { .buf = "", .pos = 0, .count = 0 };
    size_t visited = zset_foreach(zs, collect_cb, &state);
    assert(visited == 5);
    assert(state.count == 5);
    printf("Foreach: visited %zu, collected: %s\n", visited, state.buf);

    /* Foreach with early stop */
    int stop_count = 0;
    visited = zset_foreach(zs, stop_after_two, &stop_count);
    assert(visited == 2);
    printf("Foreach early stop: OK\n");

    /* --- Clone --- */
    SortedSet* clone = zset_clone(zs);
    assert(clone != NULL);
    assert(zset_card(clone) == zset_card(zs));

    /* Mutate clone, original unaffected */
    zset_add(clone, "frank", 99.0);
    assert(zset_card(clone) == 6);
    assert(zset_card(zs) == 5);
    printf("Clone independence: OK\n");
    zset_free(clone);

    /* Remove */
    assert(zset_remove(zs, "charlie") == 1);
    assert(zset_card(zs) == 4);
    printf("Remove: OK\n");

    zset_free(zs);

    /* --- Thread safety --- */
    printf("\nStarting concurrent access test...\n");
    SortedSet* shared = zset_new();
    assert(shared != NULL);

    pthread_t threads[4];
    struct thread_arg args[4];
    for (int i = 0; i < 4; i++) {
        args[i].zs = shared;
        args[i].id = i;
        pthread_create(&threads[i], NULL, writer_thread, &args[i]);
    }
    for (int i = 0; i < 4; i++) {
        pthread_join(threads[i], NULL);
    }

    size_t final_card = zset_card(shared);
    printf("After 4 threads x 50 adds: card = %zu (expected 200)\n", final_card);
    assert(final_card == 200);

    zset_free(shared);

    /* --- Null safety --- */
    assert(zset_add(NULL, "test", 1.0) == -1);
    assert(zset_card(NULL) == 0);
    zset_free(NULL);
    assert(zset_clone(NULL) == NULL);
    printf("Null safety: OK\n");

    printf("\n=== All tests passed! ===\n");
    return 0;
}
