"""
Idempotency key processing for ride requests.
Handles creating rides with crash-resilient processing backed by PostgreSQL.
"""

import json
import uuid
import sys

import psycopg2
import psycopg2.extras
from datetime import datetime, timezone

sys.path.insert(0, '/app')
from config import DB_CONFIG


class CrashSimulation(Exception):
    """Raised to simulate a mid-request crash."""
    pass


class IdempotencyConflict(Exception):
    """Raised when a concurrent request conflicts."""
    pass


class ParameterMismatch(Exception):
    """Raised when request params don't match stored params for an existing key."""
    pass


def _get_conn():
    return psycopg2.connect(**DB_CONFIG)


def _unlock_key(key_id):
    """Best-effort unlock of an idempotency key."""
    try:
        c = _get_conn()
        c.autocommit = True
        cur = c.cursor()
        cur.execute(
            "UPDATE idempotency_keys SET locked_at = NULL WHERE id = %s",
            (key_id,)
        )
        cur.close()
        c.close()
    except Exception:
        pass


def process_ride_request(user_id, idempotency_key, request_params,
                         simulate_crash_at=None):
    """
    Process a ride request with idempotency guarantees.
    """
    conn = _get_conn()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Look up existing key
        cur.execute(
            "SELECT id, request_params, recovery_point, locked_at, "
            "       response_code, response_body "
            "FROM idempotency_keys "
            "WHERE user_id = %s AND idempotency_key = %s",
            (user_id, idempotency_key)
        )
        existing = cur.fetchone()

        if existing is not None:
            # Key already finished — return cached response
            if existing['recovery_point'] == 'finished':
                conn.commit()
                return {
                    'status_code': existing['response_code'],
                    'body': existing['response_body']
                }

            # Re-lock the key for processing
            cur.execute(
                "UPDATE idempotency_keys "
                "SET locked_at = now(), last_run_at = now() "
                "WHERE id = %s",
                (existing['id'],)
            )
            conn.commit()
            key_id = existing['id']
            recovery_point = 'started'
        else:
            # Create new idempotency key
            cur.execute(
                "INSERT INTO idempotency_keys "
                "(idempotency_key, request_method, request_params, request_path, "
                " recovery_point, user_id, locked_at, last_run_at) "
                "VALUES (%s, 'POST', %s, '/rides', 'started', %s, now(), now()) "
                "RETURNING id",
                (idempotency_key, psycopg2.extras.Json(request_params), user_id)
            )
            key_id = cur.fetchone()['id']
            conn.commit()
            recovery_point = 'started'
    finally:
        cur.close()
        conn.close()

    # Execute processing phases
    try:
        if recovery_point == 'started':
            _do_create_ride(key_id, user_id, request_params)
            if simulate_crash_at == 'ride_created':
                _unlock_key(key_id)
                raise CrashSimulation("Crash at ride_created")

        _do_create_charge(key_id, user_id)
        if simulate_crash_at == 'charge_created':
            _unlock_key(key_id)
            raise CrashSimulation("Crash at charge_created")

        return _do_finish(key_id, user_id)
    except (CrashSimulation, ParameterMismatch, IdempotencyConflict):
        raise
    except Exception:
        _unlock_key(key_id)
        raise


def _do_create_ride(key_id, user_id, params):
    """Create ride record and audit entry."""
    conn = _get_conn()
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "INSERT INTO rides "
        "(idempotency_key_id, origin_lat, origin_lon, target_lat, target_lon, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (key_id, params['origin_lat'], params['origin_lon'],
         params['target_lat'], params['target_lon'], user_id)
    )
    ride_id = cur.fetchone()['id']
    cur.execute(
        "INSERT INTO audit_records (action, data, resource_id, resource_type, user_id) "
        "VALUES ('ride_created', %s, %s, 'ride', %s)",
        (psycopg2.extras.Json(params), ride_id, user_id)
    )
    cur.execute(
        "UPDATE idempotency_keys SET recovery_point = 'ride_created' WHERE id = %s",
        (key_id,)
    )
    cur.close()
    conn.close()


def _do_create_charge(key_id, user_id):
    """Create charge and link to ride."""
    conn = _get_conn()
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id FROM rides WHERE idempotency_key_id = %s", (key_id,)
    )
    ride = cur.fetchone()
    ride_id = ride['id']
    cur.execute(
        "SELECT stripe_customer_id FROM users WHERE id = %s", (user_id,)
    )
    customer_id = cur.fetchone()['stripe_customer_id']
    charge_id = f"ch_{uuid.uuid4().hex[:24]}"
    cur.execute(
        "INSERT INTO charges (id, amount, currency, customer_id, description) "
        "VALUES (%s, 2000, 'usd', %s, %s)",
        (charge_id, customer_id, f"Charge for ride {ride_id}")
    )
    cur.execute(
        "UPDATE rides SET stripe_charge_id = %s WHERE id = %s",
        (charge_id, ride_id)
    )
    cur.execute(
        "UPDATE idempotency_keys SET recovery_point = 'charge_created' WHERE id = %s",
        (key_id,)
    )
    cur.close()
    conn.close()


def _do_finish(key_id, user_id):
    """Stage receipt job and store final response."""
    conn = _get_conn()
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT r.id AS ride_id, r.stripe_charge_id "
        "FROM rides r WHERE r.idempotency_key_id = %s",
        (key_id,)
    )
    ride = cur.fetchone()
    cur.execute(
        "INSERT INTO staged_jobs (job_name, job_args) "
        "VALUES ('send_ride_receipt', %s)",
        (psycopg2.extras.Json({
            'amount': 2000, 'currency': 'usd',
            'user_id': user_id, 'ride_id': ride['ride_id']
        }),)
    )
    response_body = {
        'ride_id': ride['ride_id'],
        'charge_id': ride['stripe_charge_id']
    }
    cur.execute(
        "UPDATE idempotency_keys "
        "SET recovery_point = 'finished', locked_at = NULL, "
        "    response_code = 201, response_body = %s "
        "WHERE id = %s",
        (psycopg2.extras.Json(response_body), key_id)
    )
    cur.close()
    conn.close()
    return {'status_code': 201, 'body': response_body}


def complete_stale_requests(staleness_threshold_seconds=300):
    """
    Find and complete requests that appear stale/abandoned.
    """
    conn = _get_conn()
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id, user_id, idempotency_key, request_params "
        "FROM idempotency_keys "
        "WHERE recovery_point != 'finished' "
        "AND last_run_at < now() - make_interval(secs => %s) "
        "AND (locked_at IS NULL "
        "     OR locked_at < now() - make_interval(secs => %s))",
        (staleness_threshold_seconds, staleness_threshold_seconds)
    )
    stale_keys = cur.fetchall()
    cur.close()
    conn.close()

    completed = 0
    for key in stale_keys:
        try:
            result = process_ride_request(
                user_id=key['user_id'],
                idempotency_key=key['idempotency_key'],
                request_params=key['request_params']
            )
            if result and result.get('status_code') == 201:
                completed += 1
        except Exception:
            pass
    return completed


def reap_old_keys(age_threshold_hours=72):
    """
    Delete finished idempotency keys older than the threshold.
    """
    conn = _get_conn()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM idempotency_keys "
        "WHERE recovery_point = 'finished' "
        "AND created_at < now() - make_interval(hours => %s)",
        (age_threshold_hours,)
    )
    reaped = cur.rowcount
    cur.close()
    conn.close()
    return reaped
