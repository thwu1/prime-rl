      ******************************************************************
      *    Account Record Layout (RECLN = 72 bytes)
      *    COMP-3 fields use packed decimal encoding.
      *    V99 / V9(4) indicate implied decimal positions.
      ******************************************************************
           05  ACCT-ID              PIC X(10).
           05  CUST-NAME            PIC X(20).
           05  ACCT-TYPE            PIC X(02).
           05  ACCT-STATUS          PIC X(01).
           05  CURR-BAL             PIC S9(11)V99 COMP-3.
           05  CREDIT-LIMIT         PIC S9(9)V99  COMP-3.
           05  INT-RATE             PIC 9(3)V9(4) COMP-3.
           05  OPEN-DATE            PIC 9(8).
           05  LAST-ACTIVITY-DT     PIC 9(8).
           05  FILLER               PIC X(06).
