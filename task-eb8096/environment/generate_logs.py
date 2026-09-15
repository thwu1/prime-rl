#!/usr/bin/env python3
"""Generate heterogeneous application logs for ClickHouse compression optimization task.

Produces verbose logs with constant boilerplate text (inflating raw size) and variable
fields drawn from pools with Zipfian distributions (compressible when structured).
"""
import random
import os
from datetime import datetime, timedelta

random.seed(42)

OUTPUT = '/app/data/raw_logs.tsv'
os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

NUM_WEB = 500000
NUM_AUTH = 250000
NUM_PAYMENT = 250000

# === Shared pools ===
_rng_ip = random.Random(100)
IPS = [
    f"{_rng_ip.randint(1,223)}.{_rng_ip.randint(0,255)}.{_rng_ip.randint(0,255)}.{_rng_ip.randint(1,254)}"
    for _ in range(2000)
]
IP_W = [1.0 / (i + 1) ** 0.7 for i in range(len(IPS))]

BASE_TIME = datetime(2024, 3, 10, 0, 0, 0)
TIME_SPAN = 4 * 86400

# === Web log pools ===
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "curl/8.4.0",
    "python-requests/2.31.0",
    "Googlebot/2.1 (+http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Go-http-client/2.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Edge/120.0.0.0",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/119.0.0.0 Mobile Safari/537.36",
    "Wget/1.21.4",
    "Java/11.0.20",
    "axios/1.6.2",
    "PostmanRuntime/7.35.0",
    "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/117.0.0.0 Safari/537.36",
    "okhttp/4.12.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Apache-HttpClient/4.5.14 (Java/17.0.9)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
]
UA_W = [1.0 / (i + 1) ** 1.2 for i in range(len(USER_AGENTS))]

METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'HEAD', 'PATCH', 'OPTIONS']
METHOD_W = [0.65, 0.15, 0.07, 0.05, 0.03, 0.03, 0.02]

PROTOCOLS = ['HTTP/1.1', 'HTTP/2.0', 'HTTP/1.0']
PROTO_W = [0.70, 0.25, 0.05]

STATUSES = [200, 201, 204, 301, 302, 304, 400, 401, 403, 404, 500, 502, 503]
STATUS_W = [0.60, 0.05, 0.03, 0.05, 0.03, 0.05, 0.04, 0.03, 0.02, 0.05, 0.02, 0.02, 0.01]

_rng_p = random.Random(200)
_pfx = ['/api/v1', '/api/v2', '/api/v3', '/static', '/assets/images',
        '/assets/css', '/assets/js', '/docs', '/health', '/metrics', '/admin']
_res = ['users', 'products', 'orders', 'payments', 'cart', 'search',
        'categories', 'reviews', 'inventory', 'shipping', 'notifications', 'settings']
_sfx = ['', '/list', '/detail', '/create', '/export']
PATHS = ['/']
for _ in range(199):
    p, r, s = _rng_p.choice(_pfx), _rng_p.choice(_res), _rng_p.choice(_sfx)
    if _rng_p.random() < 0.3:
        s = f"/{_rng_p.randint(1, 5000)}"
    PATHS.append(f"{p}/{r}{s}")
PATH_W = [1.0 / (i + 1) ** 0.8 for i in range(len(PATHS))]

REFERERS = [
    '-',
    'https://www.google.com/search?q=example+products&source=web&ei=xKz3abc',
    'https://www.google.com/',
    'https://example.com/products/featured',
    'https://example.com/',
    'https://www.bing.com/search?q=example+store&form=QBLH',
    'https://t.co/abc123def456',
    'https://www.facebook.com/share/redirect',
    'https://mail.google.com/mail/u/0/',
    'https://github.com/example/project/issues',
    'https://www.reddit.com/r/technology/comments/abc123',
    'https://news.ycombinator.com/item?id=12345678',
    'https://www.linkedin.com/feed/update/urn:li:activity:12345',
    'https://duckduckgo.com/?q=example+search&ia=web',
    'https://www.baidu.com/s?wd=example+search&rsv_spt=1',
    'https://www.yahoo.com/search?p=products+catalog',
    'https://outlook.live.com/mail/0/inbox',
    'https://slack.com/team/messages/general',
    'https://discord.com/channels/123456/789012',
    'https://www.pinterest.com/pin/create/button',
]
REF_W = [12.0] + [1.0 / (i + 1) ** 1.5 for i in range(len(REFERERS) - 1)]

# Common response sizes (power-law pool for better compression)
_rng_sz = random.Random(250)
SIZES = [_rng_sz.randint(100, 500000) for _ in range(200)]
SIZE_W = [1.0 / (i + 1) ** 0.6 for i in range(len(SIZES))]

# === Auth log pools ===
AUTH_LEVELS = ['INFO', 'WARN', 'ERROR']
AUTH_LEVEL_W = [0.85, 0.10, 0.05]

AUTH_ACTIONS = ['LOGIN', 'LOGOUT', 'TOKEN_REFRESH', 'PASSWORD_CHANGE',
                'MFA_VERIFY', 'SESSION_VALIDATE', 'ROLE_CHECK']
AUTH_ACTION_W = [0.30, 0.20, 0.20, 0.05, 0.10, 0.10, 0.05]

AUTH_RESULTS = ['SUCCESS', 'FAILURE', 'TIMEOUT']
AUTH_RESULT_W = [0.80, 0.15, 0.05]

_rng_u = random.Random(300)
_fn = ['john', 'jane', 'bob', 'alice', 'charlie', 'david', 'emma', 'frank',
       'grace', 'henry', 'ivan', 'julia', 'kate', 'leo', 'mary', 'nick',
       'olivia', 'peter', 'quinn', 'rachel', 'sam', 'tina', 'uma', 'victor',
       'wendy', 'xander', 'yara', 'zach', 'alan', 'beth']
_ln = ['smith', 'jones', 'brown', 'wilson', 'taylor', 'thomas', 'moore',
       'jackson', 'martin', 'lee', 'white', 'harris', 'clark', 'lewis',
       'young', 'hall', 'allen', 'king', 'wright', 'scott']
_us = set()
while len(_us) < 5000:
    _us.add(f"{_rng_u.choice(_fn)}.{_rng_u.choice(_ln)}{_rng_u.randint(1, 999)}")
USERNAMES = list(_us)
USER_W = [1.0 / (i + 1) ** 0.9 for i in range(len(USERNAMES))]

_rng_s = random.Random(400)
SESSIONS = [
    f"{_rng_s.randint(0,0xffffffff):08x}-{_rng_s.randint(0,0xffff):04x}-"
    f"{_rng_s.randint(0,0xffff):04x}-{_rng_s.randint(0,0xffff):04x}-"
    f"{_rng_s.randint(0,0xffffffffffff):012x}"
    for _ in range(2000)
]
SESS_W = [1.0 / (i + 1) ** 0.8 for i in range(len(SESSIONS))]

# === Payment log pools ===
PAY_LEVELS = ['INFO', 'WARN', 'ERROR', 'DEBUG']
PAY_LEVEL_W = [0.75, 0.10, 0.05, 0.10]

PAY_STATUSES = ['APPROVED', 'PENDING', 'DECLINED', 'REFUNDED', 'ERROR']
PAY_STATUS_W = [0.70, 0.10, 0.10, 0.05, 0.05]

CURRENCIES = ['USD', 'EUR', 'GBP', 'JPY', 'CAD']
CURRENCY_W = [0.50, 0.20, 0.10, 0.10, 0.10]

PROCESSORS = ['STRIPE', 'SQUARE', 'ADYEN', 'BRAINTREE']
PROC_W = [0.40, 0.25, 0.20, 0.15]

MERCHANTS = [f"MERCH-{i:04d}" for i in range(1, 501)]
MERCH_W = [1.0 / (i + 1) ** 0.8 for i in range(len(MERCHANTS))]

_rng_t = random.Random(500)
TXNS = [f"TXN-{_rng_t.randint(100000000, 999999999)}" for _ in range(5000)]
TXN_W = [1.0 / (i + 1) ** 0.7 for i in range(len(TXNS))]

# Common amounts (realistic price points for better compression)
COMMON_AMOUNTS = [0.99, 1.99, 4.99, 9.99, 14.99, 19.99, 24.99, 29.99, 39.99,
                  49.99, 59.99, 74.99, 99.99, 149.99, 199.99, 249.99, 499.99, 999.99]

# === Helpers ===
def pick(pool, weights):
    return random.choices(pool, weights, k=1)[0]

def ts():
    offset = random.randint(0, TIME_SPAN)
    return (BASE_TIME + timedelta(seconds=offset)).strftime('%Y-%m-%d %H:%M:%S')

# === Constant boilerplate suffixes ===
# These inflate the raw Body size but are NOT stored as columns in optimized tables.
# They are reconstructed via ALIAS expressions, which is the key to high compression.
WEB_SUFFIX = (
    ' server_name=webserver-prod-07.us-east-1.internal ssl_proto=TLSv1.3'
    ' ssl_cipher=TLS_AES_256_GCM_SHA384 cache_status=MISS'
    ' connection_type=keep-alive upstream_addr=10.0.1.42:8080'
    ' upstream_response_time=0.003'
    ' x_request_id=req-7f3a2b1c-d4e5-6f7a-8b9c-0d1e2f3a4b5c'
    ' x_forwarded_for=10.0.0.1 x_forwarded_proto=https'
    ' content_type=application/json; charset=utf-8'
    ' geo_country=US geo_region=us-east-1 geo_asn=AS14618'
    ' waf_action=ALLOW waf_rule_group=AWSManagedRulesCommonRuleSet'
    ' lb_target_group=arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/web-prod/50dc6c495c0c9188'
    ' x_cdn_pop=IAD89-C1 x_cache_key=/default/prod/origin'
    ' trace_sampling_rate=0.01 request_priority=normal'
    ' envoy_cluster=web-upstream-prod envoy_route=default-route-v2'
    ' ratelimit_remaining=4999 ratelimit_limit=5000 ratelimit_reset=1710072000'
    ' x_amzn_trace_id=Root=1-65ee1a21-0123456789abcdef01234567'
)

AUTH_SUFFIX = (
    ' identity_provider=internal token_type=bearer_jwt'
    ' compliance_check=passed audit_trail=enabled'
    ' session_timeout_sec=3600 client_application=web-portal-v4'
    ' device_fingerprint=fp-a3b2c1d4e5f6a7b8c9d0e1f2a3b4c5d6'
    ' geo_location=us-east-1a mfa_method=totp risk_score=0.02'
    ' risk_factors=none account_age_days=365 login_history_count=1247'
    ' failed_attempts_24h=0 policy_version=iam-v3.2.1'
    ' rbac_evaluation=standard token_lifetime_sec=3600'
    ' refresh_token_issued=true encryption_standard=AES-256-GCM'
    ' key_derivation=PBKDF2-SHA512 tls_client_cert=none'
    ' credential_rotation_due=2025-03-10 sso_provider=none'
    ' directory_server=ldap-prod-01.internal directory_response_ms=2'
    ' auth_pipeline_version=v4.2.1 request_origin=web-portal'
    ' saml_assertion_id=_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8'
)

PAY_SUFFIX = (
    ' | gateway_response_code=OK | risk_assessment_result=PASS'
    ' | fraud_score=0.00 | settlement_currency=USD'
    ' | reconciliation_id=RECON-BATCH-20240312'
    ' | pci_compliance=PCI-DSS-v4.0 | pci_scope=SAQ-D'
    ' | three_ds_version=2.2.0 | three_ds_status=AUTHENTICATED'
    ' | aml_check=CLEARED | aml_provider=refinitiv-world-check'
    ' | tax_amount=0.00 | tax_jurisdiction=US-VA'
    ' | interchange_fee=0.0195 | network_fee=0.0010'
    ' | authorization_code=AUTH-839271'
    ' | acquirer_reference=ACQ-20240312-7829'
    ' | card_network=VISA | card_funding=CREDIT'
    ' | merchant_category_code=5411 | pos_entry_mode=ECOM'
    ' | batch_settlement_id=BATCH-20240312-US-001 | clearing_network=VisaNet'
    ' | payment_channel=online | terminal_id=TERM-ECOM-001'
    ' | bin_country=US | issuer_bank=Chase | card_product=Signature'
)

# === Generate ===
print("Generating logs...")

with open(OUTPUT, 'w', buffering=8 * 1024 * 1024) as f:
    for _ in range(NUM_WEB):
        ip = pick(IPS, IP_W)
        t = ts()
        method = pick(METHODS, METHOD_W)
        path = pick(PATHS, PATH_W)
        proto = pick(PROTOCOLS, PROTO_W)
        status = pick(STATUSES, STATUS_W)
        size = pick(SIZES, SIZE_W)
        ref = pick(REFERERS, REF_W)
        ua = pick(USER_AGENTS, UA_W)
        f.write(f'{ip} - - [{t}] "{method} {path} {proto}" {status} {size} "{ref}" "{ua}"{WEB_SUFFIX}\twebserver\n')

    for _ in range(NUM_AUTH):
        t = ts()
        lvl = pick(AUTH_LEVELS, AUTH_LEVEL_W)
        action = pick(AUTH_ACTIONS, AUTH_ACTION_W)
        user = pick(USERNAMES, USER_W)
        ip = pick(IPS, IP_W)
        sess = pick(SESSIONS, SESS_W)
        result = pick(AUTH_RESULTS, AUTH_RESULT_W)
        f.write(
            f'[{t}] [{lvl}] [service=authentication-service] '
            f'[component=AuthenticationHandler] Processing authentication '
            f'{action} for user_principal={user} source_address={ip} '
            f'session={sess} authentication_result={result}'
            f'{AUTH_SUFFIX}\tauth\n'
        )

    for _ in range(NUM_PAYMENT):
        t = ts()
        lvl = pick(PAY_LEVELS, PAY_LEVEL_W)
        txn = pick(TXNS, TXN_W)
        if random.random() < 0.7:
            amount = random.choice(COMMON_AMOUNTS)
        else:
            amount = round(random.uniform(0.01, 9999.99), 2)
        currency = pick(CURRENCIES, CURRENCY_W)
        merchant = pick(MERCHANTS, MERCH_W)
        status = pick(PAY_STATUSES, PAY_STATUS_W)
        processor = pick(PROCESSORS, PROC_W)
        f.write(
            f'{t} | PAYMENT-SERVICE | {lvl} | [TransactionProcessor] '
            f'| txn_id={txn} | amount={amount:.2f} | currency_code={currency} '
            f'| merchant_account={merchant} | final_status={status} '
            f'| processor={processor}'
            f'{PAY_SUFFIX}\tpayment\n'
        )

sz = os.path.getsize(OUTPUT) / (1024 * 1024)
print(f"Generated {NUM_WEB + NUM_AUTH + NUM_PAYMENT} log entries ({sz:.1f} MB) to {OUTPUT}")
