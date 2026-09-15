#ifndef ENGINE_API_H_
#define ENGINE_API_H_


#include <stdint.h>
#include <stddef.h>

/* Opaque book context — each instance is fully independent. */
typedef struct lob_book lob_book;

/* Lifecycle */
lob_book *lob_book_create(void);
void      lob_book_destroy(lob_book *book);

/* Process a complete binary message feed.
   Writes text output (executions and query results) to output_path.
   Returns 0 on success, nonzero on error. */
int lob_process_feed(lob_book *book, const uint8_t *data, size_t len,
                     const char *output_path);

/* Individual order operations.
   Execution output is appended to an internal buffer
   retrievable via lob_get_output. */
void lob_add_order(lob_book *book, uint64_t order_id, uint8_t side,
                   uint32_t qty, uint32_t price, uint64_t trader_id);
void lob_cancel_order(lob_book *book, uint64_t order_id);
void lob_reduce_order(lob_book *book, uint64_t order_id, uint32_t reduce_qty);
void lob_replace_order(lob_book *book, uint64_t old_id, uint64_t new_id,
                       uint32_t new_qty, uint32_t new_price);

/* Queries — return values directly. */
uint32_t lob_best_bid(const lob_book *book);
uint32_t lob_best_offer(const lob_book *book);
uint32_t lob_volume_at_price(const lob_book *book, uint32_t price);
void     lob_book_depth(const lob_book *book, int *buy_levels, int *sell_levels);

/* Returns 1 if order exists (fills out-params), 0 if not found. */
int lob_order_info(const lob_book *book, uint64_t order_id,
                   uint8_t *side_out, uint32_t *price_out, uint32_t *qty_out);

/* Retrieve accumulated execution output as a null-terminated string.
   Returns NULL if empty.  Pointer valid until next lob_ call on this book. */
const char *lob_get_output(const lob_book *book);

/* Clear the output buffer. */
void lob_clear_output(lob_book *book);

#endif /* ENGINE_API_H_ */
