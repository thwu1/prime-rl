#ifndef PROTOCOL_H_
#define PROTOCOL_H_


#include <stdint.h>

/* Message type codes */
#define MSG_ADD_ORDER  'A'
#define MSG_CANCEL     'X'
#define MSG_REDUCE     'D'
#define MSG_REPLACE    'U'
#define MSG_QUERY      'Q'

/* Side constants */
#define SIDE_BUY  0
#define SIDE_SELL 1

/* Query type constants */
#define QUERY_BEST_BID     0
#define QUERY_BEST_OFFER   1
#define QUERY_VOL_AT_PRICE 2
#define QUERY_BOOK_DEPTH   3
#define QUERY_ORDER_INFO   4

/* Payload sizes (bytes after the 1-byte type code) */
#define ADD_PAYLOAD_SIZE     25
#define CANCEL_PAYLOAD_SIZE   8
#define REDUCE_PAYLOAD_SIZE  12
#define REPLACE_PAYLOAD_SIZE 24
#define QUERY_PAYLOAD_SIZE   17

/* Price range: [1, MAX_PRICE] in hundredths (e.g. 10050 = $100.50) */
#define MAX_PRICE 10000000

/* Upper bound on total orders that may be submitted */
#define MAX_TOTAL_ORDERS 2000000

#endif /* PROTOCOL_H_ */
