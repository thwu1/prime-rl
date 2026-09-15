A legacy COBOL batch program at `/app/cobol/DAILYPOST.cbl` processes daily financial transactions against customer accounts. The program reads sorted binary fixed-width record files with COMP-3 (packed decimal) encoded monetary and rate fields, applies business rules for six transaction types with multiple rejection paths, and produces three output files: updated accounts, exception records for rejected transactions, and a batch control totals summary.

Record layouts are defined in copybooks at `/app/cobol/copybooks/`. Binary input data is at `/app/data/accounts.dat` and `/app/data/txns.dat`. No expected output files are provided.

GnuCOBOL compiler (`cobc`) and binary analysis tools (`xxd`) are installed and can be used to study the program's runtime behavior against the input data.

Write a self-contained Python program at `/app/posting.py` that natively reimplements the COBOL batch processing logic and produces byte-identical output at:
- `/app/output/accounts_out.dat`
- `/app/output/exceptions.dat`
- `/app/output/summary.dat`

Your implementation must compute all results using its own arithmetic and I/O logic — it must not invoke external compilers or execute external programs. Pay close attention to how the COBOL program handles interest calculations, COMP-3 encoding semantics (signed vs. unsigned sign nibbles), and the control totals accumulation pattern.