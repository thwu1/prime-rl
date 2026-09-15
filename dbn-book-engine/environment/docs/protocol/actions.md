# Event Actions

The `action` field is a single ASCII character identifying the event type.

| Code | Name   | Description                                          |
|------|--------|------------------------------------------------------|
| A    | Add    | New order added to the book                          |
| C    | Cancel | Existing order removed from the book                 |
| M    | Modify | Existing order's price and/or size updated           |
| T    | Trade  | Trade execution event (informational only)           |
| F    | Fill   | Partial or complete fill reducing order size          |
| R    | Clear  | All orders for the instrument removed                |

## Side Values

| Code | Name |
|------|------|
| B    | Bid (buy side)  |
| A    | Ask (sell side)  |
| N    | None / not applicable |
