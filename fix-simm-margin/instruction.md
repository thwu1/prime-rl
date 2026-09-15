The files under `/app/` implement an ISDA SIMM v2.5 1-Day Holding Period delta margin calculator for non-cleared OTC derivatives. The project uses Apache Ant for building with configuration split across `/app/build.xml` and `/app/build.properties`.

Build: `cd /app && ant compile`
Run: `java -cp /app/build SimmCalculator /app/portfolio.csv`

The program reads a CRIF (Common Risk Interchange Format) portfolio CSV from `/app/portfolio.csv` with columns `ProductClass,RiskType,Qualifier,Bucket,Label1,Label2,AmountUSD`. It computes initial margin across six risk classes (Interest Rate, FX, Credit Qualifying, Credit Non-Qualifying, Equity, Commodity) plus Base Correlation, aggregated per product class and summed. Output is a single integer (the total SIMM margin) to stdout.

The project contains defects in both the Ant build configuration and Java source code. Build configuration defects prevent successful compilation via `ant compile`. Source code defects produce incorrect numerical results. Some source defects affect individual risk classes while others only manifest during multi-class or multi-product aggregation.

After all defects are resolved, the calculator must produce these exact results for the provided portfolio:

- Single IR (USD, 2w, OIS, 4M): `76000000`
- Single IR (EUR, 10y, Libor12m, 35M): `560000000`
- Single CRQ (bucket 1, 800K): `16800000`
- Same-tenor IR (USD, 1y, Municipal 2M + Prime 3M): `64843812`
- Same-tenor IR (EUR, 3y, Libor3m -2M + Libor6m 5M): `48530403`
- Different-tenor IR (USD, 3m/-3M + 1y/-1M): `45671094`
- Base Correlation (CDX IG 500K/-200K, iTraxx Main 400K): `1386542`
- All FX: `10242651353`
- All IR (IRCurve + Inflation + XCcyBasis): `3134574486`
- All CRQ + Base Correlation: `79009113`
- All CRNQ: `545124809`
- All Equity: `5933432851`
- All Commodity: `16751844655`
- Credit product class: `1681012453`
- Full portfolio: `35135297361`

All modifications must be to files under `/app/`. The portfolio CSV is read-only.
