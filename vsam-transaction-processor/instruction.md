The COBOL program at `/app/txnproc.cbl` is a batch transaction processor for an indexed master file. It reads transactions from a sequential input file (`/app/transactions.dat`), applies them to an indexed master file (`/app/inventory.dat`), and writes a structured audit log to `/app/audit.log`.

The master file stores inventory records with three keys:
- Primary key: `ITEM-CODE` (PIC X(10)) — unique item identifier
- Alternate key 1: `ITEM-CATEGORY` (PIC X(15)) — product category, duplicates allowed
- Alternate key 2: `SUPPLIER-ID` (PIC X(8)) — supplier identifier, duplicates allowed

Each transaction line in `transactions.dat` is 120 characters fixed-width:
- Columns 1-3: operation code (`ADD`, `UPD`, `DEL`, `QRY`, `BRW`)
- Columns 4-13: item code
- Columns 14-28: category
- Columns 29-36: supplier ID
- Columns 37-66: item description (PIC X(30))
- Columns 67-73: unit price (PIC 9(5)V99)
- Columns 74-80: quantity on hand (PIC 9(5)V99)
- Columns 81-120: reserved/filler

Operations:
- `ADD`: Write new record. Log status `00` on success, `22` on duplicate key.
- `UPD`: Read record by primary key, then rewrite with new field values. Log `00` on success, `23` if not found.
- `DEL`: Delete record by primary key. Log `00`/`23`.
- `QRY`: Random read by primary key. Write full record fields to audit log. Log `00`/`23`.
- `BRW`: Browse by alternate key. Use the category field (columns 14-28) to START on `ITEM-CATEGORY`, then READ NEXT to retrieve all records matching that category. Write each matching record to audit log. If category is spaces, use supplier ID (columns 29-36) to browse by `SUPPLIER-ID` instead.

Audit log format — one line per operation result:
```
<OP>|<ITEM-CODE>|<STATUS>|<DETAIL>
```
Where `<DETAIL>` is:
- For `QRY`/`BRW`: the full record as `<CATEGORY>;<SUPPLIER>;<DESC>;<PRICE>;<QTY>`
- For `ADD`/`UPD`/`DEL`: empty string (line ends after `<STATUS>|`)

After all transactions, the program must write a summary line:
```
SUMMARY|<TOTAL>|<SUCCESS>|<FAILED>
```
where counts reflect transaction outcomes (status `00` or `02` = success; anything else = failed).

The program currently fails to compile and contains multiple logic errors. Fix all compilation errors, runtime bugs, and semantic defects so that it correctly processes arbitrary transaction files and produces accurate audit logs. The compiled binary must be at `/app/txnproc`. Compile with: `cobc -x -o /app/txnproc /app/txnproc.cbl`

The program must handle: empty transaction files (summary with all zeros), transactions referencing nonexistent records, duplicate primary key insertions, BRW operations that match zero records (log `BRW|<key>|23|`), and BRW operations that match multiple records (one audit line per matched record, all sharing the same operation prefix).
