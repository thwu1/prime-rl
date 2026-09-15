A PHP web application at `/app/webapp/` generates password reset tokens using PHP's `mt_rand()` function with the `MT_RAND_MT19937` mode. A batch processor runs queued password reset requests sequentially in a single PHP process, meaning all tokens in a batch share the same Mersenne Twister PRNG state seeded once at process startup.

An attacker has obtained:
- The application's source code (`/app/webapp/`)
- Debug and access log entries captured during a batch run (`/app/observed_data.json`)
- Reset tokens for two attacker-controlled accounts ("alice" and "bob")

The admin account's reset token was generated between alice's and bob's tokens in the same batch. Recover the PRNG seed, replay the Mersenne Twister state, and determine the admin's password reset token.

Write the admin's reset token to `/app/admin_token.txt`.