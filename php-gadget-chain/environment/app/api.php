<?php
/**
 * API endpoint for session validation.
 * Accepts serialized session data via POST body.
 */
error_reporting(E_ALL & ~E_NOTICE & ~E_WARNING);
require_once __DIR__ . '/libs/autoload.php';

header('Content-Type: application/json');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['error' => 'Method not allowed']);
    exit;
}

$input = json_decode(file_get_contents('php://input'), true);
if (!isset($input['session_data'])) {
    http_response_code(400);
    echo json_encode(['error' => 'Missing session_data']);
    exit;
}

$raw = base64_decode($input['session_data'], true);
if ($raw === false) {
    http_response_code(400);
    echo json_encode(['error' => 'Invalid base64']);
    exit;
}

// Restricted deserialization - only allow safe session classes
$session = @unserialize($raw, ['allowed_classes' => ['UserSession', 'UserPreferences']]);
if ($session && $session instanceof UserSession) {
    echo json_encode(['status' => 'ok', 'user' => $session->username, 'role' => $session->role]);
} else {
    http_response_code(401);
    echo json_encode(['error' => 'Invalid session']);
}
