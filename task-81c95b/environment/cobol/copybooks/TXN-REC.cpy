    05  REC-TYPE           PIC X(1).
    05  TXN-ACCT-ID        PIC X(12).
    05  TXN-ID             PIC X(16).
    05  TXN-BODY.
      10  TXN-DOM.
        15  TXN-CODE       PIC X(4).
        15  TXN-AMOUNT     PIC S9(9)V99  COMP-3.
        15  TXN-TS         PIC 9(14).
        15  CHANNEL        PIC X(4).
        15  DOM-FILLER     PIC X(23).
      10  TXN-FX REDEFINES TXN-DOM.
        15  FX-CODE        PIC X(4).
        15  FX-LOCAL-AMT   PIC S9(9)V99  COMP-3.
        15  FX-TS          PIC 9(14).
        15  FX-RATE        PIC 9V9(6) COMP-3.
        15  FX-CURRENCY    PIC X(3).
        15  FX-ORIG-AMT    PIC S9(9)V99  COMP-3.
        15  FX-FILLER      PIC X(14).
      10  TXN-ADJ REDEFINES TXN-DOM.
        15  ADJ-CODE       PIC X(4).
        15  ADJ-AMOUNT     PIC S9(9)V99  COMP-3.
        15  ADJ-TS         PIC 9(14).
        15  ADJ-ORIG-TXN   PIC X(16).
        15  ADJ-REASON     PIC X(4).
        15  ADJ-FILLER     PIC X(7).
