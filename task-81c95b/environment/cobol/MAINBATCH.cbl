       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINBATCH.

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
           SELECT SUM-FILE  ASSIGN TO "out/summary.dat"
               ORGANIZATION IS SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCT-FILE RECORD CONTAINS 66 CHARACTERS.
       01  ACCT-IN-REC.
           COPY "ACCOUNT-REC.cpy".

       FD  TXN-FILE  RECORD CONTAINS 80 CHARACTERS.
       01  TXN-IN-REC.
           COPY "TXN-REC.cpy".

       FD  ACCT-OUT  RECORD CONTAINS 66 CHARACTERS.
       01  ACCT-OUT-REC.
           COPY "ACCOUNT-REC.cpy".

       FD  EXC-FILE  RECORD CONTAINS 80 CHARACTERS.
       01  EXC-REC.
           COPY "TXN-REC.cpy".

       FD  SUM-FILE  RECORD CONTAINS 58 CHARACTERS.
       01  SUM-OUT-REC.
           COPY "SUMMARY-REC.cpy".

       WORKING-STORAGE SECTION.
       77  EOF-ACCT         PIC X     VALUE "N".
       77  EOF-TXN          PIC X     VALUE "N".
       77  TODAY            PIC 9(8)  VALUE 20250115.
       77  NEW-BAL          PIC S9(11)V99 COMP-3.

       77  WS-TS            PIC 9(14).
       77  WS-TS-DATE       PIC 9(8).
       77  WS-MILLION       PIC 9(7)  VALUE 1000000.
       77  WS-NEG-LIMIT     PIC S9(11)V99 COMP-3.

       77  WS-INTEREST      PIC S9(9)V99 COMP-3.
       77  WS-RATE-TIER     PIC 9(1).
       77  WS-FEE           PIC S9(9)V99 COMP-3.
       77  WS-FX-LOCAL      PIC S9(9)V99 COMP-3.
       77  WS-TXN-NET       PIC S9(11)V99 COMP-3.

       01  WS-SUM-REC.
           COPY "SUMMARY-REC.cpy".

       PROCEDURE DIVISION.
       MAIN.
           OPEN INPUT  ACCT-FILE TXN-FILE
                OUTPUT ACCT-OUT EXC-FILE SUM-FILE
           PERFORM READ-NEXT-TXN
           PERFORM UNTIL EOF-ACCT = "Y"
              READ ACCT-FILE
                  AT END MOVE "Y" TO EOF-ACCT
              NOT AT END
                 PERFORM INIT-SUMMARY
                 PERFORM APPLY-TODAYS-TXNS
                 PERFORM CALC-INTEREST
                 PERFORM ASSESS-FEE
                 PERFORM WRITE-SUMMARY
                 WRITE ACCT-OUT-REC FROM ACCT-IN-REC
              END-READ
           END-PERFORM
           CLOSE ACCT-FILE TXN-FILE ACCT-OUT EXC-FILE SUM-FILE
           GOBACK.

       READ-NEXT-TXN.
           READ TXN-FILE
              AT END MOVE "Y" TO EOF-TXN
           END-READ.

       INIT-SUMMARY.
           INITIALIZE WS-SUM-REC
           MOVE ACCT-ID OF ACCT-IN-REC
                TO SUM-ACCT-ID OF WS-SUM-REC.

       APPLY-TODAYS-TXNS.
           PERFORM UNTIL EOF-TXN = "Y"
                    OR TXN-ACCT-ID OF TXN-IN-REC >
                       ACCT-ID OF ACCT-IN-REC
              IF TXN-ACCT-ID OF TXN-IN-REC <
                 ACCT-ID OF ACCT-IN-REC
                 PERFORM READ-NEXT-TXN
              ELSE
                 EVALUATE REC-TYPE OF TXN-IN-REC
                    WHEN "D"
                       PERFORM PROCESS-DOMESTIC
                    WHEN "F"
                       PERFORM PROCESS-FOREIGN
                    WHEN "A"
                       PERFORM PROCESS-ADJUST
                 END-EVALUATE
                 PERFORM READ-NEXT-TXN
              END-IF
           END-PERFORM.

       PROCESS-DOMESTIC.
           MOVE TXN-TS OF TXN-IN-REC TO WS-TS
           COMPUTE WS-TS-DATE = WS-TS / WS-MILLION

           IF WS-TS-DATE = TODAY
              EVALUATE TXN-CODE OF TXN-IN-REC
                 WHEN "DEPO"
                    ADD TXN-AMOUNT OF TXN-IN-REC
                        TO CURR-BAL OF ACCT-IN-REC
                    MOVE TXN-AMOUNT OF TXN-IN-REC
                         TO WS-TXN-NET

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
                       COMPUTE WS-TXN-NET =
                               0 - TXN-AMOUNT OF TXN-IN-REC
                    ELSE
                       WRITE EXC-REC FROM TXN-IN-REC
                       MOVE 0 TO WS-TXN-NET
                    END-IF

                 WHEN "FEE "
                    ADD TXN-AMOUNT OF TXN-IN-REC
                        TO CURR-BAL OF ACCT-IN-REC
                    MOVE TXN-AMOUNT OF TXN-IN-REC
                         TO WS-TXN-NET

                 WHEN "INT "
                    ADD TXN-AMOUNT OF TXN-IN-REC
                        TO CURR-BAL OF ACCT-IN-REC
                    MOVE TXN-AMOUNT OF TXN-IN-REC
                         TO WS-TXN-NET

                 WHEN "REV "
                    SUBTRACT TXN-AMOUNT OF TXN-IN-REC
                        FROM CURR-BAL OF ACCT-IN-REC
                    COMPUTE WS-TXN-NET =
                            0 - TXN-AMOUNT OF TXN-IN-REC

                 WHEN OTHER
                    MOVE 0 TO WS-TXN-NET
              END-EVALUATE

              ADD 1 TO SUM-DOM-COUNT OF WS-SUM-REC
              ADD WS-TXN-NET TO SUM-DOM-NET OF WS-SUM-REC
              ADD 1 TO TXN-COUNT OF ACCT-IN-REC
           END-IF.

       PROCESS-FOREIGN.
           MOVE FX-TS OF TXN-IN-REC TO WS-TS
           COMPUTE WS-TS-DATE = WS-TS / WS-MILLION

           IF WS-TS-DATE = TODAY
              COMPUTE WS-FX-LOCAL ROUNDED =
                      FX-ORIG-AMT OF TXN-IN-REC
                      * FX-RATE OF TXN-IN-REC

              EVALUATE FX-CODE OF TXN-IN-REC
                 WHEN "FXBY"
                    SUBTRACT WS-FX-LOCAL FROM
                             CURR-BAL OF ACCT-IN-REC
                    COMPUTE WS-TXN-NET = 0 - WS-FX-LOCAL

                 WHEN "FXSL"
                    ADD WS-FX-LOCAL TO
                        CURR-BAL OF ACCT-IN-REC
                    MOVE WS-FX-LOCAL TO WS-TXN-NET
              END-EVALUATE

              ADD 1 TO SUM-FX-COUNT OF WS-SUM-REC
              ADD WS-TXN-NET TO SUM-FX-NET OF WS-SUM-REC
              ADD 1 TO TXN-COUNT OF ACCT-IN-REC
           END-IF.

       PROCESS-ADJUST.
           MOVE ADJ-TS OF TXN-IN-REC TO WS-TS
           COMPUTE WS-TS-DATE = WS-TS / WS-MILLION

           IF WS-TS-DATE = TODAY
              ADD ADJ-AMOUNT OF TXN-IN-REC
                  TO CURR-BAL OF ACCT-IN-REC

              ADD 1 TO SUM-ADJ-COUNT OF WS-SUM-REC
              ADD ADJ-AMOUNT OF TXN-IN-REC
                  TO SUM-ADJ-NET OF WS-SUM-REC
              ADD 1 TO TXN-COUNT OF ACCT-IN-REC
           END-IF.

       CALC-INTEREST.
           CALL "CALCRATE" USING PRODUCT OF ACCT-IN-REC
                                 CURR-BAL OF ACCT-IN-REC
                                 WS-INTEREST
                                 WS-RATE-TIER

           ADD WS-INTEREST TO CURR-BAL OF ACCT-IN-REC
           MOVE WS-INTEREST TO LAST-INTEREST OF ACCT-IN-REC
           MOVE WS-INTEREST TO SUM-INTEREST OF WS-SUM-REC.

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

           SUBTRACT WS-FEE FROM CURR-BAL OF ACCT-IN-REC
           MOVE WS-FEE TO SUM-FEE OF WS-SUM-REC.

       WRITE-SUMMARY.
           MOVE CURR-BAL OF ACCT-IN-REC
                TO SUM-FINAL-BAL OF WS-SUM-REC
           WRITE SUM-OUT-REC FROM WS-SUM-REC.
