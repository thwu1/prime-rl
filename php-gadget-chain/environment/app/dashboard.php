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

if (!$session || !isset($session->username)) {
    header('Location: /login.php');
    exit;
}
?>
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard - Acme Widget Store</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }
        .nav { background: #333; padding: 10px 20px; color: white; margin-bottom: 20px; border-radius: 5px; }
        .nav a { color: #4fc3f7; text-decoration: none; margin-right: 15px; }
        .panel { background: #f5f5f5; padding: 20px; border-radius: 5px; margin: 15px 0; }
    </style>
</head>
<body>
<div class="nav">
    <strong>Acme Widget Store</strong>
    <a href="/">Home</a>
    <a href="/dashboard.php">Dashboard</a>
    <span style="float:right">Welcome, <?= htmlspecialchars($session->username) ?></span>
</div>

<h1>User Dashboard</h1>
<div class="panel">
    <h3>Account Information</h3>
    <p>Username: <?= htmlspecialchars($session->username) ?></p>
    <p>Role: <?= htmlspecialchars($session->role ?? 'user') ?></p>
</div>

<div class="panel">
    <h3>Recent Orders</h3>
    <p>No recent orders.</p>
</div>
</body>
</html>
