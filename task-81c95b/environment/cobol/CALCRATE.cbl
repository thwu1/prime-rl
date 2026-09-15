       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALCRATE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       77  WS-ANNUAL-RATE   PIC 9V9(4).

       LINKAGE SECTION.
       01  LK-PRODUCT       PIC X(4).
       01  LK-CURR-BAL      PIC S9(11)V99 COMP-3.
       01  LK-INTEREST      PIC S9(9)V99 COMP-3.
       01  LK-RATE-TIER     PIC 9(1).

       PROCEDURE DIVISION USING LK-PRODUCT LK-CURR-BAL
                                LK-INTEREST LK-RATE-TIER.
       MAIN-PARA.
           IF LK-CURR-BAL <= 0
              MOVE 0 TO LK-INTEREST
              MOVE 0 TO LK-RATE-TIER
              GOBACK
           END-IF

           EVALUATE LK-PRODUCT
              WHEN "SAVE"
                 IF LK-CURR-BAL >= 10000.00
                    MOVE 4.7500 TO WS-ANNUAL-RATE
                    MOVE 3 TO LK-RATE-TIER
                 ELSE
                    IF LK-CURR-BAL >= 1000.00
                       MOVE 4.5000 TO WS-ANNUAL-RATE
                       MOVE 2 TO LK-RATE-TIER
                    ELSE
                       MOVE 2.0000 TO WS-ANNUAL-RATE
                       MOVE 1 TO LK-RATE-TIER
                    END-IF
                 END-IF

              WHEN "CHCK"
                 IF LK-CURR-BAL >= 5000.00
                    MOVE 1.0000 TO WS-ANNUAL-RATE
                    MOVE 2 TO LK-RATE-TIER
                 ELSE
                    MOVE 0.0000 TO WS-ANNUAL-RATE
                    MOVE 1 TO LK-RATE-TIER
                 END-IF

              WHEN "PREM"
                 IF LK-CURR-BAL >= 500.00
                    MOVE 5.5000 TO WS-ANNUAL-RATE
                    MOVE 2 TO LK-RATE-TIER
                 ELSE
                    MOVE 3.0000 TO WS-ANNUAL-RATE
                    MOVE 1 TO LK-RATE-TIER
                 END-IF

              WHEN "MMKT"
                 IF LK-CURR-BAL >= 10000.00
                    MOVE 5.0000 TO WS-ANNUAL-RATE
                    MOVE 3 TO LK-RATE-TIER
                 ELSE
                    IF LK-CURR-BAL >= 5000.00
                       MOVE 3.5000 TO WS-ANNUAL-RATE
                       MOVE 2 TO LK-RATE-TIER
                    ELSE
                       MOVE 2.0000 TO WS-ANNUAL-RATE
                       MOVE 1 TO LK-RATE-TIER
                    END-IF
                 END-IF

              WHEN OTHER
                 MOVE 0.0000 TO WS-ANNUAL-RATE
                 MOVE 0 TO LK-RATE-TIER
           END-EVALUATE

           IF WS-ANNUAL-RATE = 0
              MOVE 0 TO LK-INTEREST
              GOBACK
           END-IF

           COMPUTE LK-INTEREST ROUNDED =
                   LK-CURR-BAL * WS-ANNUAL-RATE / 1200

           GOBACK.
