-- Schema for idempotency key system with atomic phases and recovery points

CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE CHECK (char_length(email) <= 255),
    stripe_customer_id TEXT NOT NULL UNIQUE CHECK (char_length(stripe_customer_id) <= 50)
);

CREATE TABLE idempotency_keys (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key TEXT NOT NULL CHECK (char_length(idempotency_key) <= 100),
    last_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ DEFAULT now(),
    request_method TEXT NOT NULL CHECK (char_length(request_method) <= 10),
    request_params JSONB NOT NULL,
    request_path TEXT NOT NULL CHECK (char_length(request_path) <= 100),
    response_code INT,
    response_body JSONB,
    recovery_point TEXT NOT NULL CHECK (char_length(recovery_point) <= 50),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX idempotency_keys_user_id_idempotency_key
    ON idempotency_keys (user_id, idempotency_key);

CREATE TABLE rides (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key_id BIGINT REFERENCES idempotency_keys(id) ON DELETE SET NULL,
    origin_lat NUMERIC(13, 10) NOT NULL,
    origin_lon NUMERIC(13, 10) NOT NULL,
    target_lat NUMERIC(13, 10) NOT NULL,
    target_lon NUMERIC(13, 10) NOT NULL,
    stripe_charge_id TEXT UNIQUE CHECK (char_length(stripe_charge_id) <= 50),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT rides_user_id_idempotency_key_unique UNIQUE (user_id, idempotency_key_id)
);

CREATE INDEX rides_idempotency_key_id ON rides (idempotency_key_id)
    WHERE idempotency_key_id IS NOT NULL;

CREATE TABLE audit_records (
    id BIGSERIAL PRIMARY KEY,
    action TEXT NOT NULL CHECK (char_length(action) <= 50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    data JSONB NOT NULL,
    resource_id BIGINT NOT NULL,
    resource_type TEXT NOT NULL CHECK (char_length(resource_type) <= 50),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE staged_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    job_args JSONB NOT NULL
);

CREATE TABLE charges (
    id TEXT PRIMARY KEY,
    amount INT NOT NULL,
    currency TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
