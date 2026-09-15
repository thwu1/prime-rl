CREATE TABLE ledger_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    fund_flow TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    account_from TEXT NOT NULL,
    account_to TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    currency TEXT NOT NULL,
    business_id TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);

\copy ledger_events FROM '/tmp/events.csv' WITH (FORMAT csv, HEADER true)

CREATE INDEX idx_ledger_txn ON ledger_events(transaction_id);
CREATE INDEX idx_ledger_flow ON ledger_events(fund_flow);
CREATE INDEX idx_ledger_type ON ledger_events(event_type);
CREATE INDEX idx_ledger_acct_from ON ledger_events(account_from);
CREATE INDEX idx_ledger_acct_to ON ledger_events(account_to);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ledger;
