<?php
/**
 * Configuration import endpoint.
 * Accepts serialized configuration data via POST, protected by HMAC signature.
 */
error_reporting(E_ALL & ~E_NOTICE & ~E_WARNING);
require_once __DIR__ . '/libs/autoload.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo 'POST required';
    exit;
}

$payload = $_POST['config_data'] ?? '';
$signature = $_POST['signature'] ?? '';

if (empty($payload) || empty($signature)) {
    http_response_code(400);
    echo 'Missing config_data or signature';
    exit;
}

// Load HMAC key
$hmac_key = @file_get_contents('/app/hmac_secret.key');
if ($hmac_key === false) {
    http_response_code(500);
    echo 'Server configuration error';
    exit;
}

// Verify HMAC signature before processing
$expected_sig = hash_hmac('sha256', $payload, trim($hmac_key));
if (!hash_equals($expected_sig, $signature)) {
    http_response_code(403);
    echo 'Invalid signature';
    exit;
}

$raw = base64_decode($payload, true);
if ($raw === false) {
    http_response_code(400);
    echo 'Invalid base64 data';
    exit;
}

// HMAC-verified data is trusted
$config = @unserialize($raw);
if ($config) {
    echo 'Configuration imported successfully';
} else {
    http_response_code(400);
    echo 'Invalid configuration data';
}
