#!/bin/bash

set -euo pipefail

# Install solution source
cp /solution/DataflowSolver.java /app/src/DataflowSolver.java

# Update Main.java to use the DataflowSolver implementation with --dot support
cat > /app/src/Main.java << 'MAINEOF'
public class Main {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: java Main [--dot] <tac-file>");
            System.exit(1);
        }
        AnalysisEngine engine = new DataflowSolver();
        if (args[0].equals("--dot")) {
            if (args.length < 2) {
                System.err.println("Usage: java Main --dot <tac-file>");
                System.exit(1);
            }
            System.out.println(engine.toDot(args[1]));
        } else {
            System.out.println(engine.analyze(args[0]));
        }
    }
}
MAINEOF

# Build using make
cd /app
make compile

# Create JAR with manifest
echo "Main-Class: Main" > /app/build/MANIFEST.MF
jar cfm /app/analyzer.jar /app/build/MANIFEST.MF -C /app/build .

# Create batch analysis script
cat > /app/analyze.sh << 'SCRIPTEOF'
#!/bin/bash
set -euo pipefail
DIR="$1"
mkdir -p /app/results

for f in "$DIR"/*.tac; do
    [ -f "$f" ] || continue
    JSON=$(java -jar /app/analyzer.jar "$f")
    METHOD=$(echo "$JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['method'])")
    echo "$JSON" > "/app/results/${METHOD}.json"
    java -jar /app/analyzer.jar --dot "$f" | dot -Tsvg > "/app/results/${METHOD}_cfg.svg"
done

# Combine all JSON results into array
python3 -c "
import json, glob
results = []
for f in sorted(glob.glob('/app/results/*.json')):
    with open(f) as fh:
        results.append(json.load(fh))
print(json.dumps(results))
"
SCRIPTEOF
chmod +x /app/analyze.sh

# Verify on all provided TAC files
echo "Verifying analysis on all TAC files..." >&2
/app/analyze.sh /app/tac > /dev/null
echo "Solution installed and verified." >&2
