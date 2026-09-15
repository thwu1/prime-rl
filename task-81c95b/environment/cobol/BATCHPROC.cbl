       IDENTIFICATION DIVISION.
       PROGRAM-ID. BATCHPROC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCT-FILE ASSIGN TO "data/accounts.dat"
               ORGANIZATION IS SEQUENTIAL.
           SELECT TXN-FILE  ASSIGN TO "data/txns.dat"
               ORGANIZATION IS SEQUENTIAL.
           SELECT ACCT-OUT  ASSIGN TO "out/accounts_out.dat"
               ORGANIZATION IS SEQUENTIAL.
           SELECT EXC-FILE  ASSIGN TO "out/exceptions.dat"
               ORGANIZATION IS SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCT-FILE RECORD CONTAINS 58 CHARACTERS.
       01  ACCT-IN-REC.
           COPY "ACCOUNT-REC.cpy".

       FD  TXN-FILE  RECORD CONTAINS 72 CHARACTERS.
       01  TXN-IN-REC.
           COPY "TXN-REC.cpy".

       FD  ACCT-OUT  RECORD CONTAINS 58 CHARACTERS.
       01  ACCT-OUT-REC.
           COPY "ACCOUNT-REC.cpy".

       FD  EXC-FILE  RECORD CONTAINS 72 CHARACTERS.
       01  EXC-REC.
           COPY "TXN-REC.cpy".

       WORKING-STORAGE SECTION.
       77  EOF-ACCT         PIC X     VALUE "N".
       77  EOF-TXN          PIC X     VALUE "N".
       77  TODAY            PIC 9(8)  VALUE 20250115.
       77  NEW-BAL          PIC S9(11)V99 COMP-3.

       77  WS-TS            PIC 9(14).
       77  WS-TS-DATE       PIC 9(8).
       77  WS-MILLION       PIC 9(7)  VALUE 1000000.
       77  WS-NEG-LIMIT     PIC S9(11)V99 COMP-3.

       77  WS-ANNUAL-RATE   PIC 9V9(4).
       77  WS-INTEREST      PIC S9(11)V99 COMP-3.
       77  WS-FEE           PIC S9(9)V99 COMP-3.

       PROCEDURE DIVISION.
       MAIN.
           OPEN INPUT  ACCT-FILE TXN-FILE
                OUTPUT ACCT-OUT EXC-FILE
           PERFORM READ-NEXT-TXN
           PERFORM UNTIL EOF-ACCT = "Y"
              READ ACCT-FILE
                  AT END MOVE "Y" TO EOF-ACCT
              NOT AT END
                 PERFORM APPLY-TODAYS-TXNS
                 PERFORM CALC-INTEREST
                 PERFORM ASSESS-FEE
                 WRITE ACCT-OUT-REC FROM ACCT-IN-REC
              END-READ
           END-PERFORM
           CLOSE ACCT-FILE TXN-FILE ACCT-OUT EXC-FILE
           GOBACK.

       READ-NEXT-TXN.
           READ TXN-FILE
              AT END MOVE "Y" TO EOF-TXN
           END-READ.

       APPLY-TODAYS-TXNS.
           PERFORM UNTIL EOF-TXN = "Y"
                    OR ACCT-ID OF TXN-IN-REC >
                       ACCT-ID OF ACCT-IN-REC
              IF ACCT-ID OF TXN-IN-REC <
                 ACCT-ID OF ACCT-IN-REC
                 PERFORM READ-NEXT-TXN
              ELSE
                 MOVE TXN-TS OF TXN-IN-REC TO WS-TS
                 COMPUTE WS-TS-DATE = WS-TS / WS-MILLION

                 IF WS-TS-DATE = TODAY
                    EVALUATE TXN-CODE OF TXN-IN-REC
                       WHEN "DEPO"
                          ADD TXN-AMOUNT OF TXN-IN-REC
                              TO CURR-BAL OF ACCT-IN-REC

                       WHEN "WDRW"
                          COMPUTE NEW-BAL =
                                  CURR-BAL OF ACCT-IN-REC
                                  - TXN-AMOUNT OF TXN-IN-REC
                          COMPUTE WS-NEG-LIMIT =
                                  0 - OVERDRAFT-LIMIT
                                      OF ACCT-IN-REC
                          IF NEW-BAL >= WS-NEG-LIMIT
                             MOVE NEW-BAL
                                  TO CURR-BAL OF ACCT-IN-REC
                          ELSE
                             WRITE EXC-REC FROM TXN-IN-REC
                          END-IF

                       WHEN "FEE "
                          ADD TXN-AMOUNT OF TXN-IN-REC
                              TO CURR-BAL OF ACCT-IN-REC

                       WHEN "INT "
                          ADD TXN-AMOUNT OF TXN-IN-REC
                              TO CURR-BAL OF ACCT-IN-REC

                       WHEN "REV "
                          SUBTRACT TXN-AMOUNT OF TXN-IN-REC
                              FROM CURR-BAL OF ACCT-IN-REC
                    END-EVALUATE
                 END-IF

                 PERFORM READ-NEXT-TXN
              END-IF
           END-PERFORM.

       CALC-INTEREST.
           IF CURR-BAL OF ACCT-IN-REC <= 0
              MOVE 0 TO WS-INTEREST
           ELSE
              EVALUATE PRODUCT OF ACCT-IN-REC
                 WHEN "SAVE"
                    IF CURR-BAL OF ACCT-IN-REC >= 1000.00
                       MOVE 4.5000 TO WS-ANNUAL-RATE
                    ELSE
                       MOVE 2.0000 TO WS-ANNUAL-RATE
                    END-IF

                 WHEN "CHCK"
                    IF CURR-BAL OF ACCT-IN-REC >= 5000.00
                       MOVE 1.0000 TO WS-ANNUAL-RATE
                    ELSE
                       MOVE 0.0000 TO WS-ANNUAL-RATE
                    END-IF

                 WHEN "PREM"
                    IF CURR-BAL OF ACCT-IN-REC >= 500.00
                       MOVE 5.5000 TO WS-ANNUAL-RATE
                    ELSE
                       MOVE 3.0000 TO WS-ANNUAL-RATE
                    END-IF

                 WHEN "MMKT"
                    IF CURR-BAL OF ACCT-IN-REC >= 10000.00
                       MOVE 5.0000 TO WS-ANNUAL-RATE
                    ELSE
                       IF CURR-BAL OF ACCT-IN-REC >= 5000.00
                          MOVE 3.5000 TO WS-ANNUAL-RATE
                       ELSE
                          MOVE 2.0000 TO WS-ANNUAL-RATE
                       END-IF
                    END-IF

                 WHEN OTHER
                    MOVE 0.0000 TO WS-ANNUAL-RATE
              END-EVALUATE

              COMPUTE WS-INTEREST ROUNDED =
                      CURR-BAL OF ACCT-IN-REC
                      * WS-ANNUAL-RATE / 1200
           END-IF

           ADD WS-INTEREST TO CURR-BAL OF ACCT-IN-REC.

       ASSESS-FEE.
           MOVE 0 TO WS-FEE

           EVALUATE PRODUCT OF ACCT-IN-REC
              WHEN "CHCK"
                 IF CURR-BAL OF ACCT-IN-REC < 1500.00
                    MOVE 15.00 TO WS-FEE
                 END-IF

              WHEN "SAVE"
                 IF CURR-BAL OF ACCT-IN-REC < 300.00
                    MOVE 5.00 TO WS-FEE
                 END-IF

              WHEN "PREM"
                 MOVE 25.00 TO WS-FEE

              WHEN "MMKT"
                 IF CURR-BAL OF ACCT-IN-REC < 2500.00
                    MOVE 10.00 TO WS-FEE
                 END-IF
           END-EVALUATE

           SUBTRACT WS-FEE FROM CURR-BAL OF ACCT-IN-REC.
