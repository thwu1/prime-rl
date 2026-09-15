<?php

require_once __DIR__ . '/token_generator.php';

/**
 * BatchResetProcessor - Processes queued password reset requests.
 *
 * This script runs as a scheduled task and processes all pending reset
 * requests sequentially within a single PHP process invocation.
 * The Mersenne Twister PRNG is seeded once automatically at process
 * startup; the same PRNG state is shared across all requests
 * processed in this batch.
 *
 * Usage: php batch_reset_processor.php
 */

$pending_requests = ['alice', 'admin', 'bob'];

$results = [];
foreach ($pending_requests as $username) {
    $result = TokenGenerator::processResetRequest($username);
    $results[] = $result;

    // Application debug log (writes to stderr / error_log)
    error_log(sprintf(
        "[BatchReset] user=%s tracking_id=%s audit_id=%s csrf=%s",
        $result['username'],
        $result['tracking_id'],
        $result['audit_id'],
        $result['csrf_nonce']
    ));
}

// Persist tokens to database
foreach ($results as $r) {
    // In production this would be a prepared statement insert
    error_log(sprintf(
        "[DB] INSERT INTO reset_tokens (username, token) VALUES ('%s', '%s')",
        $r['username'],
        $r['reset_token']
    ));
}
