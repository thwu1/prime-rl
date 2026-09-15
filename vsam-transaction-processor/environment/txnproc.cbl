      *
      * Transaction Processor for Indexed Inventory Master File
      * Reads transactions from sequential file, applies to indexed file,
      * produces audit log.
      *
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TXNPROC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INVENTORY-FILE
               ASSIGN TO "inventory.dat"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS SEQUENTIAL
               RECORD KEY IS ITEM-CODE
               FILE STATUS IS WS-INV-STATUS.

           SELECT TRANSACTION-FILE
               ASSIGN TO "transactions.dat"
               ORGANIZATION IS LINE SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-TXN-STATUS.

           SELECT AUDIT-FILE
               ASSIGN TO "audit.log"
               ORGANIZATION IS LINE SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL
               FILE STATUS IS WS-AUD-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD INVENTORY-FILE.
       01 INVENTORY-RECORD.
           05 ITEM-CODE            PIC X(10).
           05 ITEM-CATEGORY        PIC X(15).
           05 SUPPLIER-ID          PIC X(8).
           05 ITEM-DESCRIPTION     PIC X(30).
           05 UNIT-PRICE           PIC 9(5)V99.
           05 QUANTITY-ON-HAND     PIC 9(5)V99.

       FD TRANSACTION-FILE.
       01 TRANSACTION-RECORD.
           05 TXN-OP-CODE         PIC X(3).
           05 TXN-ITEM-CODE       PIC X(10).
           05 TXN-CATEGORY        PIC X(15).
           05 TXN-SUPPLIER-ID     PIC X(8).
           05 TXN-DESCRIPTION     PIC X(30).
           05 TXN-UNIT-PRICE      PIC 9(5)V99.
           05 TXN-QUANTITY        PIC 9(5)V99.
           05 TXN-FILLER          PIC X(40).

       FD AUDIT-FILE.
       01 AUDIT-RECORD             PIC X(200).

       WORKING-STORAGE SECTION.
       01 WS-INV-STATUS            PIC XX.
           88 WS-INV-SUCCESS       VALUE "00".
           88 WS-INV-DUP-ALT      VALUE "02".
           88 WS-INV-EOF           VALUE "10".
           88 WS-INV-NOT-FOUND    VALUE "32".
           88 WS-INV-DUP-KEY      VALUE "22".

       01 WS-TXN-STATUS            PIC XX.
           88 WS-TXN-SUCCESS      VALUE "00".
           88 WS-TXN-EOF          VALUE "10".

       01 WS-AUD-STATUS            PIC XX.

       01 WS-TOTAL-COUNT           PIC 9(6) VALUE 0.
       01 WS-SUCCESS-COUNT         PIC 9(6) VALUE 0.
       01 WS-FAIL-COUNT            PIC 9(6) VALUE 0.

       01 WS-AUDIT-LINE            PIC X(200).
       01 WS-DETAIL-STR            PIC X(150).

       01 WS-BROWSE-CATEGORY       PIC X(15).
       01 WS-BROWSE-SUPPLIER       PIC X(8).
       01 WS-BROWSE-MODE           PIC 9.
           88 WS-BROWSE-BY-CAT    VALUE 1.
           88 WS-BROWSE-BY-SUP    VALUE 2.
       01 WS-BROWSE-FOUND          PIC 9 VALUE 0.
       01 WS-BROWSE-MATCH          PIC 9 VALUE 0.

       01 WS-PRICE-DISP            PIC Z(4)9.99.
       01 WS-QTY-DISP              PIC Z(4)9.99.

       01 WS-TOTAL-DISP            PIC Z(5)9.
       01 WS-SUCC-DISP             PIC Z(5)9.
       01 WS-FAIL-DISP             PIC Z(5)9.

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM OPEN-FILES
           PERFORM PROCESS-TRANSACTIONS
           PERFORM WRITE-SUMMARY
           PERFORM CLOSE-FILES
           STOP RUN.

       OPEN-FILES.
           OPEN I-O INVENTORY-FILE
           IF NOT WS-INV-SUCCESS
               IF WS-INV-STATUS = "35"
                   OPEN OUTPUT INVENTORY-FILE
                   CLOSE INVENTORY-FILE
                   OPEN I-O INVENTORY-FILE
               ELSE
                   DISPLAY "Error opening inventory: "
                       WS-INV-STATUS
                   STOP RUN
               END-IF
           END-IF

           OPEN INPUT TRANSACTION-FILE
           IF NOT WS-TXN-SUCCESS
               DISPLAY "Error opening transactions: "
                   WS-TXN-STATUS
               STOP RUN

           OPEN OUTPUT AUDIT-FILE
           IF WS-AUD-STATUS NOT = "00"
               DISPLAY "Error opening audit log: "
                   WS-AUD-STATUS
               STOP RUN
           END-IF.

       PROCESS-TRANSACTIONS.
           PERFORM READ-NEXT-TXN
           PERFORM UNTIL WS-TXN-EOF
               ADD 1 TO WS-TOTAL-COUNT
               EVALUATE TXN-OP-CODE
                   WHEN "ADD" PERFORM DO-ADD
                   WHEN "UPD" PERFORM DO-UPDATE
                   WHEN "DEL" PERFORM DO-DELETE
                   WHEN "QRY" PERFORM DO-QUERY
                   WHEN "BRW" PERFORM DO-BROWSE
                   WHEN OTHER
                       STRING "ERR|" TXN-ITEM-CODE "|99|"
                           DELIMITED BY SIZE
                           INTO WS-AUDIT-LINE
                       PERFORM WRITE-AUDIT
                       ADD 1 TO WS-FAIL-COUNT
               END-EVALUATE
               PERFORM READ-NEXT-TXN
           END-PERFORM.

       READ-NEXT-TXN.
           READ TRANSACTION-FILE
               AT END CONTINUE
           END-READ.

       DO-ADD.
           MOVE TXN-ITEM-CODE TO ITEM-CODE
           MOVE TXN-CATEGORY TO ITEM-CATEGORY
           MOVE TXN-SUPPLIER-ID TO SUPPLIER-ID
           MOVE TXN-DESCRIPTION TO ITEM-DESCRIPTION
           MOVE TXN-UNIT-PRICE TO UNIT-PRICE
           MOVE TXN-QUANTITY TO QUANTITY-ON-HAND

           WRITE INVENTORY-RECORD
           IF WS-INV-SUCCESS OR WS-INV-DUP-ALT
               STRING "ADD|" TXN-ITEM-CODE "|"
                   WS-INV-STATUS "|"
                   DELIMITED BY SIZE
                   INTO WS-AUDIT-LINE
               PERFORM WRITE-AUDIT
               ADD 1 TO WS-SUCCESS-COUNT
           ELSE
               STRING "ADD|" TXN-ITEM-CODE "|"
                   WS-INV-STATUS "|"
                   DELIMITED BY SIZE
                   INTO WS-AUDIT-LINE
               PERFORM WRITE-AUDIT
               ADD 1 TO WS-FAIL-COUNT
           END-IF.

       DO-UPDATE.
           MOVE TXN-ITEM-CODE TO ITEM-CODE
           MOVE TXN-CATEGORY TO ITEM-CATEGORY
           MOVE TXN-SUPPLIER-ID TO SUPPLIER-ID
           MOVE TXN-DESCRIPTION TO ITEM-DESCRIPTION
           MOVE TXN-UNIT-PRICE TO UNIT-PRICE
           MOVE TXN-QUANTITY TO QUANTITY-ON-HAND

           REWRITE INVENTORY-RECORD
               INVALID KEY
                   STRING "UPD|" TXN-ITEM-CODE "|"
                       WS-INV-STATUS "|"
                       DELIMITED BY SIZE
                       INTO WS-AUDIT-LINE
                   PERFORM WRITE-AUDIT
                   ADD 1 TO WS-FAIL-COUNT
               NOT INVALID KEY
                   STRING "UPD|" TXN-ITEM-CODE "|"
                       WS-INV-STATUS "|"
                       DELIMITED BY SIZE
                       INTO WS-AUDIT-LINE
                   PERFORM WRITE-AUDIT
                   ADD 1 TO WS-SUCCESS-COUNT
           END-REWRITE.

       DO-DELETE.
           MOVE TXN-ITEM-CODE TO ITEM-CODE

           DELETE INVENTORY-FILE
               INVALID KEY
                   STRING "DEL|" TXN-ITEM-CODE "|"
                       WS-INV-STATUS "|"
                       DELIMITED BY SIZE
                       INTO WS-AUDIT-LINE
                   PERFORM WRITE-AUDIT
                   ADD 1 TO WS-FAIL-COUNT
               NOT INVALID KEY
                   STRING "DEL|" TXN-ITEM-CODE "|"
                       WS-INV-STATUS "|"
                       DELIMITED BY SIZE
                       INTO WS-AUDIT-LINE
                   PERFORM WRITE-AUDIT
                   ADD 1 TO WS-SUCCESS-COUNT
           END-DELETE.

       DO-QUERY.
           MOVE TXN-ITEM-CODE TO ITEM-CODE

           READ INVENTORY-FILE
               INVALID KEY
                   STRING "QRY|" TXN-ITEM-CODE "|"
                       WS-INV-STATUS "|"
                       DELIMITED BY SIZE
                       INTO WS-AUDIT-LINE
                   PERFORM WRITE-AUDIT
                   ADD 1 TO WS-FAIL-COUNT
               NOT INVALID KEY
                   PERFORM FORMAT-DETAIL
                   STRING "QRY|" TXN-ITEM-CODE "|"
                       WS-INV-STATUS "|" WS-DETAIL-STR
                       DELIMITED BY SIZE
                       INTO WS-AUDIT-LINE
                   PERFORM WRITE-AUDIT
                   ADD 1 TO WS-SUCCESS-COUNT
           END-READ.

       DO-BROWSE.
           MOVE 0 TO WS-BROWSE-FOUND
           IF TXN-CATEGORY NOT = SPACES
               SET WS-BROWSE-BY-CAT TO TRUE
               MOVE TXN-CATEGORY TO WS-BROWSE-CATEGORY
               MOVE TXN-CATEGORY TO ITEM-CATEGORY
               START INVENTORY-FILE
                   KEY >= ITEM-CODE
                   INVALID KEY
                       STRING "BRW|" TXN-ITEM-CODE "|23|"
                           DELIMITED BY SIZE
                           INTO WS-AUDIT-LINE
                       PERFORM WRITE-AUDIT
                       ADD 1 TO WS-FAIL-COUNT
                       EXIT PARAGRAPH
               END-START
           ELSE
               SET WS-BROWSE-BY-SUP TO TRUE
               MOVE TXN-SUPPLIER-ID TO WS-BROWSE-SUPPLIER
               MOVE TXN-SUPPLIER-ID TO SUPPLIER-ID
               START INVENTORY-FILE
                   KEY >= ITEM-CODE
                   INVALID KEY
                       STRING "BRW|" TXN-ITEM-CODE "|23|"
                           DELIMITED BY SIZE
                           INTO WS-AUDIT-LINE
                       PERFORM WRITE-AUDIT
                       ADD 1 TO WS-FAIL-COUNT
                       EXIT PARAGRAPH
               END-START
           END-IF

           PERFORM READ-BROWSE-NEXT
               UNTIL WS-INV-EOF
           IF WS-BROWSE-FOUND = 0
               STRING "BRW|" TXN-ITEM-CODE "|23|"
                   DELIMITED BY SIZE
                   INTO WS-AUDIT-LINE
               PERFORM WRITE-AUDIT
               ADD 1 TO WS-FAIL-COUNT
           ELSE
               ADD 1 TO WS-SUCCESS-COUNT
           END-IF.

       READ-BROWSE-NEXT.
           READ INVENTORY-FILE NEXT
               AT END
                   CONTINUE
               NOT AT END
                   MOVE 0 TO WS-BROWSE-MATCH
                   IF WS-BROWSE-BY-CAT
                       IF ITEM-CATEGORY = WS-BROWSE-CATEGORY
                           MOVE 1 TO WS-BROWSE-MATCH
                       END-IF
                   END-IF
                   IF WS-BROWSE-BY-SUP
                       IF SUPPLIER-ID = WS-BROWSE-SUPPLIER
                           MOVE 1 TO WS-BROWSE-MATCH
                       END-IF
                   END-IF
                   IF WS-BROWSE-MATCH = 1
                       MOVE 1 TO WS-BROWSE-FOUND
                       PERFORM FORMAT-DETAIL
                       STRING "BRW|" ITEM-CODE "|"
                           WS-INV-STATUS "|" WS-DETAIL-STR
                           DELIMITED BY SIZE
                           INTO WS-AUDIT-LINE
                       PERFORM WRITE-AUDIT
                   END-IF
           END-READ.

       FORMAT-DETAIL.
           MOVE UNIT-PRICE TO WS-PRICE-DISP
           MOVE QUANTITY-ON-HAND TO WS-QTY-DISP
           STRING
               ITEM-CATEGORY ";" SUPPLIER-ID ";"
               ITEM-DESCRIPTION ";"
               WS-PRICE-DISP ";" WS-QTY-DISP
               DELIMITED BY SIZE
               INTO WS-DETAIL-STR.

       WRITE-AUDIT.
           WRITE AUDIT-RECORD FROM WS-AUDIT-LINE.

       WRITE-SUMMARY.
           MOVE WS-TOTAL-COUNT TO WS-TOTAL-DISP
           MOVE WS-SUCCESS-COUNT TO WS-SUCC-DISP
           MOVE WS-FAIL-COUNT TO WS-FAIL-DISP
           STRING "SUMMARY|" WS-TOTAL-DISP "|"
               WS-SUCC-DISP "|" WS-FAIL-DISP
               DELIMITED BY SIZE
               INTO WS-AUDIT-LINE
           PERFORM WRITE-AUDIT.

       CLOSE-FILES.
           CLOSE INVENTORY-FILE
           CLOSE TRANSACTION-FILE
           CLOSE AUDIT-FILE.
