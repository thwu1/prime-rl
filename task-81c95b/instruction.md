A COBOL batch system at `/app/cobol/` processes daily banking transactions. The compiled binary `/app/cobol/mainbatch` reads `data/accounts.dat` and `data/txns.dat`, applies transactions, computes interest and fees, then writes `out/accounts_out.dat`, `out/exceptions.dat`, and `out/summary.dat`.

Source for `MAINBATCH.cbl` and all copybooks (record layouts) is available under `/app/cobol/` and `/app/cobol/copybooks/`. However, the `CALCRATE` interest rate subprogram source has been lost — only compiled code remains embedded in the binaries. From `MAINBATCH.cbl`, the call signature is visible: `CALL "CALCRATE" USING LK-PRODUCT LK-CURR-BAL LK-INTEREST LK-RATE-TIER`. A probe utility `/app/cobol/proberates` accepts `PRODUCT` and `BALANCE` environment variables (dollar amount as string, e.g. `PRODUCT=SAVE BALANCE=5000.00 /app/cobol/proberates`) to test CALCRATE with arbitrary inputs.

Pre-generated sample data is at `/app/data/`. GnuCOBOL is installed for reference runs.

Create `/app/migrate/batch_post.py` that reads the same binary inputs from `data/` (relative to CWD) and produces byte-identical output files in `out/`. The migration must faithfully replicate all business logic present in `MAINBATCH.cbl` and the lost `CALCRATE` subprogram. Study the COBOL source, copybooks, and probe utility to understand how all data is encoded, how records are structured, and how the batch processing works end to end.

Validation compares SHA-256 checksums of all output files across multiple datasets including boundary cases and rounding edge cases.