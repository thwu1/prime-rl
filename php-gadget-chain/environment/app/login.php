<?php
error_reporting(E_ALL & ~E_NOTICE & ~E_WARNING);
require_once __DIR__ . '/libs/autoload.php';

$error = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $username = $_POST['username'] ?? '';
    $password = $_POST['password'] ?? '';

    if ($username === 'guest' && $password === 'guest123') {
        $session = new UserSession($username, 'user');
        $cookie_value = base64_encode(serialize($session));
        setcookie('user_session', $cookie_value, time() + 3600, '/');
        header('Location: /dashboard.php');
        exit;
    }
    $error = "Invalid credentials";
}
?>
<!DOCTYPE html>
<html>
<head>
    <title>Login - Acme Widget Store</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 500px; margin: 80px auto; padding: 0 20px; }
        form { background: #f5f5f5; padding: 30px; border-radius: 5px; }
        input { display: block; width: 100%; padding: 10px; margin: 8px 0 16px 0; box-sizing: border-box; }
        button { background: #333; color: white; padding: 12px 24px; border: none; cursor: pointer; border-radius: 3px; }
        .error { color: #d32f2f; margin-bottom: 15px; }
        .hint { color: #666; font-size: 0.9em; margin-top: 15px; }
    </style>
</head>
<body>
<h1>Login</h1>
<?php if ($error): ?>
    <p class="error"><?= htmlspecialchars($error) ?></p>
<?php endif; ?>
<form method="POST">
    <label>Username</label>
    <input type="text" name="username" required>
    <label>Password</label>
    <input type="password" name="password" required>
    <button type="submit">Sign In</button>
</form>
<p class="hint">Demo account: guest / guest123</p>
</body>
</html>
