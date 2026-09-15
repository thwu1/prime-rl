      ******************************************************************
      * Program     : DAILYPOST.CBL
      * Application : Banking Batch System
      * Type        : Batch COBOL Program
      * Function    : Daily Transaction Posting
      *
      * Description : Reads sequential account and transaction files.
      *               Both files are sorted by account ID ascending.
      *               For each account, applies matching transactions:
      *                 DEPO - deposit (add to balance)
      *                 WDRW - withdrawal (subtract, check credit limit)
      *                 PYMT - payment (add to balance)
      *                 FEES - fee charge (subtract from balance)
      *                 INTC - daily interest accrual compounded over
      *                        30 days using 360-day convention;
      *                        each daily accrual uses ROUNDED
      *                 REVR - reversal (subtract from balance)
      *               Writes updated accounts, exception records for
      *               rejected transactions, and a batch control
      *               totals summary record.
      *
      * Rejection Codes:
      *   1001 - Transaction for nonexistent account (orphan)
      *   1002 - Account not active (status <> 'A')
      *   1003 - Insufficient funds / overlimit
      *   1004 - Unknown transaction type
      *   1005 - Transaction date before account open date
      *
      * Record Formats:
      *   Account   - 72 bytes (see ACCOUNT-REC.cpy)
      *   Txn       - 64 bytes (see TXN-REC.cpy)
      *   Exception - 88 bytes (64 txn data + 4 reason + 20 desc)
      *   Summary   - 80 bytes (control totals)
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DAILYPOST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCT-FILE ASSIGN TO "data/accounts.dat"
               ORGANIZATION IS SEQUENTIAL.
           SELECT TXN-FILE  ASSIGN TO "data/txns.dat"
               ORGANIZATION IS SEQUENTIAL.
           SELECT ACCT-OUT  ASSIGN TO "output/accounts_out.dat"
               ORGANIZATION IS SEQUENTIAL.
           SELECT EXC-FILE  ASSIGN TO "output/exceptions.dat"
               ORGANIZATION IS SEQUENTIAL.
           SELECT SUMM-FILE ASSIGN TO "output/summary.dat"
               ORGANIZATION IS SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCT-FILE RECORD CONTAINS 72 CHARACTERS.
       01  ACCT-IN-REC.
           COPY "ACCOUNT-REC.cpy".

       FD  TXN-FILE  RECORD CONTAINS 64 CHARACTERS.
       01  TXN-IN-REC.
           COPY "TXN-REC.cpy".

       FD  ACCT-OUT  RECORD CONTAINS 72 CHARACTERS.
       01  ACCT-OUT-REC              PIC X(72).

       FD  EXC-FILE  RECORD CONTAINS 88 CHARACTERS.
       01  EXC-REC.
           05  EXC-TXN-DATA          PIC X(64).
           05  EXC-REASON-CD         PIC 9(04).
           05  EXC-REASON-DESC       PIC X(20).

       FD  SUMM-FILE RECORD CONTAINS 80 CHARACTERS.
       01  SUMM-REC.
           05  SUMM-LABEL            PIC X(04).
           05  SUMM-TOT-DEBITS       PIC S9(11)V99 COMP-3.
           05  SUMM-TOT-CREDITS      PIC S9(11)V99 COMP-3.
           05  SUMM-ACCT-COUNT       PIC 9(07) COMP-3.
           05  SUMM-EXC-COUNT        PIC 9(07) COMP-3.
           05  SUMM-TXN-COUNT        PIC 9(07) COMP-3.
           05  SUMM-HASH-TOTAL       PIC S9(13)V99 COMP-3.
           05  FILLER                PIC X(42).

       WORKING-STORAGE SECTION.
       77  EOF-ACCT          PIC X      VALUE "N".
       77  EOF-TXN           PIC X      VALUE "N".
       77  WS-NEW-BAL        PIC S9(11)V99 COMP-3.
       77  WS-NEG-LIMIT      PIC S9(11)V99 COMP-3.
       77  WS-DAILY-INT      PIC S9(11)V99 COMP-3.
       77  WS-DAY            PIC 9(03).
       77  WS-TOT-DEBITS     PIC S9(11)V99 COMP-3 VALUE 0.
       77  WS-TOT-CREDITS    PIC S9(11)V99 COMP-3 VALUE 0.
       77  WS-ACCT-COUNT     PIC 9(07) COMP-3 VALUE 0.
       77  WS-EXC-COUNT      PIC 9(07) COMP-3 VALUE 0.
       77  WS-TXN-APPLIED    PIC 9(07) COMP-3 VALUE 0.
       77  WS-HASH-TOTAL     PIC S9(13)V99 COMP-3 VALUE 0.

       PROCEDURE DIVISION.
       MAIN.
           OPEN INPUT  ACCT-FILE TXN-FILE
                OUTPUT ACCT-OUT EXC-FILE SUMM-FILE
           PERFORM READ-NEXT-TXN
           PERFORM UNTIL EOF-ACCT = "Y"
              READ ACCT-FILE
                  AT END MOVE "Y" TO EOF-ACCT
              NOT AT END
                 PERFORM PROCESS-ACCOUNT-TXNS
                 ADD CURR-BAL TO WS-HASH-TOTAL
                 ADD 1 TO WS-ACCT-COUNT
                 WRITE ACCT-OUT-REC FROM ACCT-IN-REC
              END-READ
           END-PERFORM
           PERFORM WRITE-SUMMARY
           CLOSE ACCT-FILE TXN-FILE ACCT-OUT EXC-FILE SUMM-FILE
           GOBACK.

       READ-NEXT-TXN.
           READ TXN-FILE
              AT END MOVE "Y" TO EOF-TXN
           END-READ.

       PROCESS-ACCOUNT-TXNS.
           PERFORM UNTIL EOF-TXN = "Y"
                    OR TXN-ACCT-ID > ACCT-ID
              IF TXN-ACCT-ID < ACCT-ID
                 MOVE TXN-IN-REC TO EXC-TXN-DATA
                 MOVE 1001 TO EXC-REASON-CD
                 MOVE "NO MATCHING ACCOUNT" TO EXC-REASON-DESC
                 WRITE EXC-REC
                 ADD 1 TO WS-EXC-COUNT
                 PERFORM READ-NEXT-TXN
              ELSE
                 IF ACCT-STATUS NOT = "A"
                    MOVE TXN-IN-REC TO EXC-TXN-DATA
                    MOVE 1002 TO EXC-REASON-CD
                    MOVE "ACCOUNT NOT ACTIVE" TO EXC-REASON-DESC
                    WRITE EXC-REC
                    ADD 1 TO WS-EXC-COUNT
                    PERFORM READ-NEXT-TXN
                 ELSE
                    IF TXN-DATE < OPEN-DATE
                       MOVE TXN-IN-REC TO EXC-TXN-DATA
                       MOVE 1005 TO EXC-REASON-CD
                       MOVE "TXN BEFORE OPEN DATE" TO EXC-REASON-DESC
                       WRITE EXC-REC
                       ADD 1 TO WS-EXC-COUNT
                       PERFORM READ-NEXT-TXN
                    ELSE
                       PERFORM APPLY-TRANSACTION
                       PERFORM READ-NEXT-TXN
                    END-IF
                 END-IF
              END-IF
           END-PERFORM.

       APPLY-TRANSACTION.
           EVALUATE TXN-TYPE
              WHEN "DEPO"
                 ADD TXN-AMOUNT TO CURR-BAL
                 ADD TXN-AMOUNT TO WS-TOT-DEBITS
                 ADD 1 TO WS-TXN-APPLIED
              WHEN "WDRW"
                 COMPUTE WS-NEW-BAL = CURR-BAL - TXN-AMOUNT
                 COMPUTE WS-NEG-LIMIT = 0 - CREDIT-LIMIT
                 IF WS-NEW-BAL >= WS-NEG-LIMIT
                    MOVE WS-NEW-BAL TO CURR-BAL
                    ADD TXN-AMOUNT TO WS-TOT-CREDITS
                    ADD 1 TO WS-TXN-APPLIED
                 ELSE
                    MOVE TXN-IN-REC TO EXC-TXN-DATA
                    MOVE 1003 TO EXC-REASON-CD
                    MOVE "INSUFFICIENT FUNDS" TO EXC-REASON-DESC
                    WRITE EXC-REC
                    ADD 1 TO WS-EXC-COUNT
                 END-IF
              WHEN "PYMT"
                 ADD TXN-AMOUNT TO CURR-BAL
                 ADD TXN-AMOUNT TO WS-TOT-DEBITS
                 ADD 1 TO WS-TXN-APPLIED
              WHEN "FEES"
                 SUBTRACT TXN-AMOUNT FROM CURR-BAL
                 ADD TXN-AMOUNT TO WS-TOT-CREDITS
                 ADD 1 TO WS-TXN-APPLIED
              WHEN "INTC"
                 PERFORM VARYING WS-DAY FROM 1 BY 1
                    UNTIL WS-DAY > 30
                    COMPUTE WS-DAILY-INT ROUNDED
                       = CURR-BAL * INT-RATE / 36000
                    ADD WS-DAILY-INT TO CURR-BAL
                 END-PERFORM
                 ADD 1 TO WS-TXN-APPLIED
              WHEN "REVR"
                 SUBTRACT TXN-AMOUNT FROM CURR-BAL
                 ADD TXN-AMOUNT TO WS-TOT-CREDITS
                 ADD 1 TO WS-TXN-APPLIED
              WHEN OTHER
                 MOVE TXN-IN-REC TO EXC-TXN-DATA
                 MOVE 1004 TO EXC-REASON-CD
                 MOVE "UNKNOWN TXN TYPE" TO EXC-REASON-DESC
                 WRITE EXC-REC
                 ADD 1 TO WS-EXC-COUNT
           END-EVALUATE
           MOVE TXN-DATE TO LAST-ACTIVITY-DT.

       WRITE-SUMMARY.
           MOVE SPACES TO SUMM-REC
           MOVE "CTRL" TO SUMM-LABEL
           MOVE WS-TOT-DEBITS TO SUMM-TOT-DEBITS
           MOVE WS-TOT-CREDITS TO SUMM-TOT-CREDITS
           MOVE WS-ACCT-COUNT TO SUMM-ACCT-COUNT
           MOVE WS-EXC-COUNT TO SUMM-EXC-COUNT
           MOVE WS-TXN-APPLIED TO SUMM-TXN-COUNT
           MOVE WS-HASH-TOTAL TO SUMM-HASH-TOTAL
           WRITE SUMM-REC.
