<?php
// Debug file reader utility
// Part of webapp-utils package
header('Content-Type: text/plain');
$file = isset($_GET['f']) ? $_GET['f'] : '';
if (empty($file)) {
    echo "webapp-utils file reader v1.0\n";
    echo "Usage: ?f=<filepath>\n";
    exit;
}
if (!file_exists($file)) {
    echo "Error: file not found\n";
    exit;
}
echo file_get_contents($file);
?>
