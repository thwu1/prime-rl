#!/usr/bin/env node
/**
 * DNS exfiltration interceptor for telemetry-helper backdoor analysis.
 *
 * Monkey-patches dns.resolve() before loading the backdoor module to
 * capture all outbound DNS queries. Triggers the backdoor with a canary
 * environment variable and logs intercepted queries to dns_exfil_log.json.
 *
 */

'use strict';

const dns = require('dns');
const fs = require('fs');

const intercepted = [];

// Monkey-patch dns.resolve BEFORE loading the backdoor module
const _origResolve = dns.resolve;
dns.resolve = function(hostname, typeOrCb, callback) {
    const recType = typeof typeOrCb === 'string' ? typeOrCb : 'A';
    const cb = typeof typeOrCb === 'function' ? typeOrCb : callback;

    intercepted.push({
        hostname: hostname,
        type: recType,
        timestamp: Date.now(),
    });

    // Return a fake result so the backdoor thinks it succeeded
    if (typeof cb === 'function') cb(null, ['127.0.0.1']);
};

// Set the canary env var that the backdoor will exfiltrate
process.env.SECRET_CANARY = 'TB_AUDIT_2024_f7e3a';

// Load and start the ORIGINAL (unpatched) backdoor module
const { createClient } = require('/app/.originals/telemetry-helper');
const client = createClient();
client.start();

// The backdoor uses setTimeout with 5-15s random delay.
// Wait 20s to ensure it fires, then write the log.
setTimeout(() => {
    client.stop();

    const output = {
        intercepted_queries: intercepted,
        total_queries: intercepted.length,
        capture_method: 'dns.resolve monkey-patch instrumentation',
        trigger_env: { SECRET_CANARY: 'TB_AUDIT_2024_f7e3a' },
    };

    fs.writeFileSync(
        '/app/dns_exfil_log.json',
        JSON.stringify(output, null, 2) + '\n'
    );

    console.log('Captured ' + intercepted.length + ' DNS exfiltration queries');
    intercepted.forEach(function(q) {
        console.log('  -> ' + q.hostname);
    });

    process.exit(0);
}, 20000);
