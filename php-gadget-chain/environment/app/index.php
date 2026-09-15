<?php
error_reporting(E_ALL & ~E_NOTICE & ~E_WARNING);
require_once __DIR__ . '/libs/autoload.php';

$session = null;
if (isset($_COOKIE['user_session'])) {
    $raw = base64_decode($_COOKIE['user_session'], true);
    if ($raw !== false) {
        $session = @unserialize($raw);
    }
}
?>
<!DOCTYPE html>
<html>
<head>
    <title>Acme Widget Store</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }
        .product { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px; }
        .nav { background: #333; padding: 10px 20px; color: white; margin-bottom: 20px; border-radius: 5px; }
        .nav a { color: #4fc3f7; text-decoration: none; margin-right: 15px; }
    </style>
</head>
<body>
<div class="nav">
    <strong>Acme Widget Store</strong>
    <?php if ($session && isset($session->username)): ?>
        <a href="/dashboard.php">Dashboard</a>
        <span style="float:right">Welcome, <?= htmlspecialchars($session->username) ?></span>
    <?php else: ?>
        <a href="/login.php">Login</a>
    <?php endif; ?>
</div>

<h1>Featured Products</h1>
<!-- Internal note: legacy class library at /libs/ needs migration to new framework -->

<div class="product">
    <h3>Premium Widget A</h3>
    <p>High-quality industrial widget. Price: $29.99</p>
</div>

<div class="product">
    <h3>Deluxe Widget B</h3>
    <p>Enhanced widget with extended warranty. Price: $49.99</p>
</div>

<div class="product">
    <h3>Enterprise Widget C</h3>
    <p>Enterprise-grade widget solution. Price: $99.99</p>
</div>

<footer style="margin-top: 40px; color: #888; font-size: 0.9em;">
    <p>&copy; 2024 Acme Widget Store. All rights reserved.</p>
</footer>
</body>
</html>
