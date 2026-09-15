      ******************************************************************
      *    Transaction Record Layout (RECLN = 64 bytes)
      *    TXN-AMOUNT uses signed packed decimal (COMP-3).
      ******************************************************************
           05  TXN-ACCT-ID          PIC X(10).
           05  TXN-ID               PIC X(12).
           05  TXN-TYPE             PIC X(04).
           05  TXN-AMOUNT           PIC S9(9)V99 COMP-3.
           05  TXN-DATE             PIC 9(8).
           05  TXN-DESC             PIC X(20).
           05  FILLER               PIC X(04).
