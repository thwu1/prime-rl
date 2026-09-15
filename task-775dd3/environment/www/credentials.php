<?php
// Internal application configuration
// Access restricted to authorized administrators only
header('Content-Type: text/plain');
echo "=== Internal Application Configuration ===\n\n";
echo "Database Host: db.internal.corp\n";
echo "Database User: webapp_admin\n";
echo "Database Pass: Pr0d_DB_2024!xK9m\n\n";
echo "Installed Debug Tools:\n";
echo "  File Reader: /usr/share/doc/webapp-utils/tools/reader.php\n";
echo "  Usage: reader.php?f=<filepath>\n\n";
echo "Sensitive Files:\n";
echo "  Application secrets: /var/secret/flag.txt\n";
?>
