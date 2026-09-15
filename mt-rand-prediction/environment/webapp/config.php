<?php

// Application configuration for the password reset token generator.
// The charset is a shuffled permutation of [0-9a-zA-Z].
define('TOKEN_CHARSET', '9aGkR1mBvXpTnHcW4QYeZfLgUhJi0DO2Fs3dtKwN5oAlSbjMxEy7PqC8rIu6Vz');
define('CSRF_LENGTH', 8);
define('TRACKING_ID_LENGTH', 12);
define('TOKEN_LENGTH', 32);
define('AUDIT_ID_LENGTH', 8);
define('JITTER_MIN', 100);
define('JITTER_MAX', 9999);
define('JITTER_COUNT', 3);
