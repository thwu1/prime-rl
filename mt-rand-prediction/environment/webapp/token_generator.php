<?php

require_once __DIR__ . '/config.php';

class TokenGenerator {
    /**
     * Generate a random string of given length using TOKEN_CHARSET.
     * Each character is selected by mt_rand(0, strlen(TOKEN_CHARSET) - 1).
     */
    private static function generateString(int $length): string {
        $charset = TOKEN_CHARSET;
        $maxIdx = strlen($charset) - 1;
        $result = '';
        for ($i = 0; $i < $length; $i++) {
            $idx = mt_rand(0, $maxIdx);
            $result .= $charset[$idx];
        }
        return $result;
    }

    /**
     * Generate JITTER_COUNT random jitter values in range [JITTER_MIN, JITTER_MAX].
     * These are used internally for request timing variance and are not exposed.
     */
    private static function generateJitter(): array {
        $values = [];
        for ($i = 0; $i < JITTER_COUNT; $i++) {
            $values[] = mt_rand(JITTER_MIN, JITTER_MAX);
        }
        return $values;
    }

    /**
     * Process a single password reset request.
     * Generates, in order:
     *   1. CSRF nonce       (CSRF_LENGTH chars)
     *   2. Tracking ID      (TRACKING_ID_LENGTH chars)
     *   3. Jitter values    (JITTER_COUNT integers)
     *   4. Reset token      (TOKEN_LENGTH chars)
     *   5. Audit ID         (AUDIT_ID_LENGTH chars)
     */
    public static function processResetRequest(string $username): array {
        $csrf_nonce  = self::generateString(CSRF_LENGTH);
        $tracking_id = self::generateString(TRACKING_ID_LENGTH);
        $jitter      = self::generateJitter();
        $reset_token = self::generateString(TOKEN_LENGTH);
        $audit_id    = self::generateString(AUDIT_ID_LENGTH);

        return [
            'username'    => $username,
            'csrf_nonce'  => $csrf_nonce,
            'tracking_id' => $tracking_id,
            'jitter'      => $jitter,
            'reset_token' => $reset_token,
            'audit_id'    => $audit_id,
        ];
    }
}
