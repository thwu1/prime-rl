#!/usr/bin/env bash

set -euo pipefail

cd /app

# --- Step 1: Fix the Maven POM ---
# Java source level must be 11+ (code uses 'var'), mainClass is wrong,
# and exec arguments are missing.
cat > pom.xml << 'POMEOF'
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.analytics</groupId>
    <artifactId>isda-cds-pricer</artifactId>
    <version>1.0-SNAPSHOT</version>
    <packaging>jar</packaging>
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    </properties>
    <build>
        <plugins>
            <plugin>
                <groupId>org.codehaus.mojo</groupId>
                <artifactId>exec-maven-plugin</artifactId>
                <version>3.1.0</version>
                <configuration>
                    <mainClass>cds.CdsPricer</mainClass>
                    <arguments>
                        <argument>/app/data</argument>
                    </arguments>
                </configuration>
            </plugin>
        </plugins>
    </build>
</project>
POMEOF

# --- Step 2: Preprocess market data ---

# Decode base64-encoded yield curve
base64 -d data/yield_curve.b64 > data/yield_curve.csv

# Transform raw trade feed to the format DataLoader expects.
# Raw feed has different field names and uses percentage/basis-point units.
jq '{
  valuation_date: .market_data.valuation_date,
  stepin_date: .market_data.stepin_date,
  recovery_rate: (.market_data.recovery_rate_pct / 100),
  notional: .portfolio.notional_usd,
  fixed_rate: (.portfolio.coupon_bps / 10000),
  model_conventions: .model_conventions,
  trades: [.portfolio.positions[] | {
    id: .trade_id,
    buy_sell: .side,
    start_date: .effective_date,
    end_date: .termination_date,
    frequency_months: (if .payment_frequency == "QUARTERLY" then 3 elif .payment_frequency == "SEMI_ANNUAL" then 6 else 12 end)
  }]
}' data/trades_raw.json > data/trades.json

# --- Step 3: Replace skeleton with complete implementation ---
cp /solution/CdsPricerImpl.java src/main/java/cds/CdsPricer.java

# --- Step 4: Fix pipeline.sh so test.sh can re-run it ---
cat > pipeline.sh << 'PIPEEOF'
#!/usr/bin/env bash
set -e
cd /app
base64 -d data/yield_curve.b64 > data/yield_curve.csv
jq '{
  valuation_date: .market_data.valuation_date,
  stepin_date: .market_data.stepin_date,
  recovery_rate: (.market_data.recovery_rate_pct / 100),
  notional: .portfolio.notional_usd,
  fixed_rate: (.portfolio.coupon_bps / 10000),
  model_conventions: .model_conventions,
  trades: [.portfolio.positions[] | {
    id: .trade_id,
    buy_sell: .side,
    start_date: .effective_date,
    end_date: .termination_date,
    frequency_months: (if .payment_frequency == "QUARTERLY" then 3 elif .payment_frequency == "SEMI_ANNUAL" then 6 else 12 end)
  }]
}' data/trades_raw.json > data/trades.json
mvn -q compile
mvn -q exec:java
PIPEEOF
chmod +x pipeline.sh

# --- Step 5: Build and run ---
mvn -q compile
mvn -q exec:java -Dexec.mainClass="cds.CdsPricer" -Dexec.args="/app/data"

echo "Solution complete. Results written to /app/results.json"
