#!/bin/bash

set -e

cd /app

# Step 1: Fix pom.xml — remove workaround dependency, add JAXB dependencies
python3 /solution/fix_pom.py

# Step 2: Fix all javax → jakarta imports (and revert incorrect jakarta.sql → javax.sql)
python3 /solution/fix_java_imports.py

# Step 3: Rewrite SecurityConfig from removed WebSecurityConfigurerAdapter
python3 /solution/fix_security_config.py

# Step 4: Fix WebConfig from removed WebMvcConfigurerAdapter
python3 /solution/fix_web_config.py

# Step 5: Selectively update string-literal class name references
python3 /solution/fix_string_literals.py

# Step 6: Fix property files
python3 /solution/fix_properties.py

# Step 7: Verify compilation succeeds
mvn compile -q -B

echo "Migration repair completed successfully."
