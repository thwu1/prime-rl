CREATE TABLE IF NOT EXISTS participants (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    service TEXT NOT NULL,
    pricing_option TEXT
);

CREATE TABLE IF NOT EXISTS billing_groups (
    id TEXT PRIMARY KEY,
    leader_id TEXT NOT NULL REFERENCES participants(id)
);

CREATE TABLE IF NOT EXISTS billing_group_members (
    group_id TEXT NOT NULL REFERENCES billing_groups(id),
    participant_id TEXT NOT NULL REFERENCES participants(id),
    PRIMARY KEY (group_id, participant_id)
);

CREATE TABLE IF NOT EXISTS rtgs_bank_volumes (
    participant_id TEXT PRIMARY KEY REFERENCES participants(id),
    payment_orders INTEGER NOT NULL,
    addressable_bics INTEGER DEFAULT 0,
    unpublished_bics INTEGER DEFAULT 0,
    multi_addressee_bics INTEGER DEFAULT 0,
    lt_within_rtgs_cross_bg INTEGER DEFAULT 0,
    lt_rtgs_to_clm_cross_bg INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rtgs_as_volumes (
    participant_id TEXT PRIMARY KEY REFERENCES participants(id),
    cash_transfer_orders INTEGER NOT NULL,
    daily_guv_eur_millions REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS t2s_activity (
    participant_id TEXT PRIMARY KEY REFERENCES participants(id),
    messages_bundled INTEGER DEFAULT 0,
    transmissions INTEGER DEFAULT 0,
    u2a_queries INTEGER DEFAULT 0,
    a2a_queries INTEGER DEFAULT 0,
    a2a_reports INTEGER DEFAULT 0,
    internal_lt INTEGER DEFAULT 0,
    intra_balance_movements INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tips_psp_volumes (
    participant_id TEXT PRIMARY KEY REFERENCES participants(id),
    dcas INTEGER NOT NULL,
    dca_aau_bics INTEGER DEFAULT 0,
    settled_ip_orig INTEGER DEFAULT 0,
    unsettled_ip_orig INTEGER DEFAULT 0,
    settled_ip_benef INTEGER DEFAULT 0,
    unsettled_ip_benef INTEGER DEFAULT 0,
    settled_recall_orig INTEGER DEFAULT 0,
    unsettled_recall_orig INTEGER DEFAULT 0,
    settled_recall_benef INTEGER DEFAULT 0,
    unsettled_recall_benef INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tips_ach_volumes (
    participant_id TEXT PRIMARY KEY REFERENCES participants(id),
    astas INTEGER NOT NULL,
    asta_aau_bics INTEGER DEFAULT 0,
    internally_settled_ip INTEGER DEFAULT 0,
    settled_ip_orig INTEGER DEFAULT 0,
    unsettled_ip_orig INTEGER DEFAULT 0,
    settled_ip_benef INTEGER DEFAULT 0,
    unsettled_ip_benef INTEGER DEFAULT 0,
    settled_recall_orig INTEGER DEFAULT 0,
    unsettled_recall_orig INTEGER DEFAULT 0,
    settled_recall_benef INTEGER DEFAULT 0,
    unsettled_recall_benef INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fee_breakdown (
    participant_id TEXT PRIMARY KEY REFERENCES participants(id),
    service TEXT NOT NULL,
    fixed_fee REAL NOT NULL DEFAULT 0,
    transaction_fee REAL NOT NULL DEFAULT 0,
    bic_fee REAL NOT NULL DEFAULT 0,
    lt_fee REAL NOT NULL DEFAULT 0,
    other_fee REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0
);
