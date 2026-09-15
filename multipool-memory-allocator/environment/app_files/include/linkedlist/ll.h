/*
 * Intrusive doubly-linked list (Linux kernel list.h style).
 * All operations are inline/macros - no separate .c file needed.
 */
#ifndef LL_H
#define LL_H

#include <stddef.h>

typedef struct ll_head {
    struct ll_head *next;
    struct ll_head *prev;
} ll_t;

#define LIST_INIT(name) ll_t name = { &(name), &(name) }

#define container_of(ptr, type, member) \
    ((type *)((char *)(ptr) - offsetof(type, member)))

#define list_entry(ptr, type, member) container_of(ptr, type, member)

#define list_for_each(pos, head) \
    for (pos = (head)->next; pos != (head); pos = pos->next)

#define list_for_each_safe(pos, n, head) \
    for (pos = (head)->next, n = pos->next; \
         pos != (head); \
         pos = n, n = pos->next)

#define list_for_each_entry(pos, head, member) \
    for (pos = list_entry((head)->next, typeof(*pos), member); \
         &pos->member != (head); \
         pos = list_entry(pos->member.next, typeof(*pos), member))

#define list_for_each_entry_safe(pos, n, head, member) \
    for (pos = list_entry((head)->next, typeof(*pos), member), \
         n = list_entry(pos->member.next, typeof(*pos), member); \
         &pos->member != (head); \
         pos = n, n = list_entry(n->member.next, typeof(*pos), member))

static inline void list_init(ll_t *head)
{
    head->next = head;
    head->prev = head;
}

static inline void __list_add(ll_t *new_node, ll_t *prev, ll_t *next)
{
    next->prev = new_node;
    new_node->next = next;
    new_node->prev = prev;
    prev->next = new_node;
}

static inline void list_add(ll_t *new_node, ll_t *head)
{
    __list_add(new_node, head, head->next);
}

static inline void list_add_tail(ll_t *new_node, ll_t *head)
{
    __list_add(new_node, head->prev, head);
}

static inline void list_insert(ll_t *new_node, ll_t *prev, ll_t *next)
{
    __list_add(new_node, prev, next);
}

static inline void list_del(ll_t *entry)
{
    entry->prev->next = entry->next;
    entry->next->prev = entry->prev;
    entry->next = NULL;
    entry->prev = NULL;
}

static inline int list_empty(const ll_t *head)
{
    return head->next == head;
}

#endif /* LL_H */
