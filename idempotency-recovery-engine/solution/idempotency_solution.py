"""
Idempotency key processing engine with atomic phases and recovery points.

Implements a DAG-based state machine where each atomic phase runs in a
SERIALIZABLE transaction with recovery points committed atomically,
enabling crash recovery on retry.
"""

import json
import uuid
import sys

import psycopg2
import psycopg2.extras
import psycopg2.errors
import psycopg2.extensions
from datetime import datetime, timezone

sys.path.insert(0, '/app')
from config import DB_CONFIG

LOCK_TIMEOUT_SECONDS = 300

RECOVERY_POINT_STARTED = 'started'
RECOVERY_POINT_RIDE_CREATED = 'ride_created'
RECOVERY_POINT_CHARGE_CREATED = 'charge_created'
RECOVERY_POINT_FINISHED = 'finished'


class CrashSimulation(Exception):
    """Raised to simulate a mid-request crash at a specific recovery point."""
    pass


class IdempotencyConflict(Exception):
    """Raised when a concurrent request conflicts with this one."""
    pass


class ParameterMismatch(Exception):
    """Raised when request params don't match stored params for an existing key."""
    pass


def get_connection():
    """Create and return a new database connection."""
    return psycopg2.connect(**DB_CONFIG)


def _atomic_phase(callback):
    """
    Execute callback within a SERIALIZABLE transaction.

    The callback receives a cursor and must return its result.
    SerializationFailure and UniqueViolation are caught and converted
    to IdempotencyConflict. All other exceptions trigger a rollback
    and are re-raised.
    """
    conn = get_connection()
    try:
        conn.autocommit = False
        conn.set_isolation_level(
            psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            result = callback(cur)
            conn.commit()
            return result
        except psycopg2.errors.SerializationFailure:
            conn.rollback()
            raise IdempotencyConflict("Serialization conflict — retry the request")
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            raise IdempotencyConflict("Unique constraint conflict — retry the request")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        conn.close()


def _unlock_key(key_id):
    """Best-effort unlock of an idempotency key so it can be retried."""
    try:
        conn = get_connection()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "UPDATE idempotency_keys SET locked_at = NULL WHERE id = %s",
            (key_id,)
        )
        cur.close()
        conn.close()
    except Exception:
        pass


def _normalize_params(params):
    """Normalize parameters to a canonical JSON string for comparison."""
    return json.dumps(params, sort_keys=True, default=str)


def process_ride_request(user_id, idempotency_key, request_params,
                         simulate_crash_at=None):
    """
    Process a ride request with idempotency guarantees.

    Uses a DAG state machine with atomic phases separated by recovery points:
        started -> ride_created -> charge_created -> finished

    Each phase runs in a SERIALIZABLE transaction. Recovery points are
    committed atomically with each phase's work, enabling crash recovery.
    """
    params_normalized = _normalize_params(request_params)

    # Phase 1: Upsert idempotency key
    def upsert_key(cur):
        cur.execute(
            "SELECT id, request_params, recovery_point, locked_at, "
            "       response_code, response_body "
            "FROM idempotency_keys "
            "WHERE user_id = %s AND idempotency_key = %s "
            "FOR UPDATE",
            (user_id, idempotency_key)
        )
        row = cur.fetchone()

        if row is not None:
            stored_normalized = _normalize_params(row['request_params'])
            if stored_normalized != params_normalized:
                raise ParameterMismatch(
                    "Request parameters do not match the stored parameters "
                    "for this idempotency key"
                )

            if row['recovery_point'] == RECOVERY_POINT_FINISHED:
                return {
                    'key_id': row['id'],
                    'recovery_point': RECOVERY_POINT_FINISHED,
                    'response': {
                        'status_code': row['response_code'],
                        'body': row['response_body'],
                    },
                }

            if row['locked_at'] is not None:
                now_utc = datetime.now(timezone.utc)
                locked_at = row['locked_at']
                if locked_at.tzinfo is None:
                    locked_at = locked_at.replace(tzinfo=timezone.utc)
                else:
                    locked_at = locked_at.astimezone(timezone.utc)
                lock_age = (now_utc - locked_at).total_seconds()
                if lock_age < LOCK_TIMEOUT_SECONDS:
                    raise IdempotencyConflict(
                        "This idempotency key is currently being processed "
                        "by another request"
                    )

            cur.execute(
                "UPDATE idempotency_keys "
                "SET locked_at = now(), last_run_at = now() "
                "WHERE id = %s",
                (row['id'],)
            )
            return {
                'key_id': row['id'],
                'recovery_point': row['recovery_point'],
                'response': None,
            }
        else:
            cur.execute(
                "INSERT INTO idempotency_keys "
                "  (idempotency_key, request_method, request_params, "
                "   request_path, recovery_point, user_id, "
                "   locked_at, last_run_at) "
                "VALUES (%s, 'POST', %s, '/rides', %s, %s, now(), now()) "
                "RETURNING id",
                (idempotency_key, psycopg2.extras.Json(request_params),
                 RECOVERY_POINT_STARTED, user_id)
            )
            key_id = cur.fetchone()['id']
            return {
                'key_id': key_id,
                'recovery_point': RECOVERY_POINT_STARTED,
                'response': None,
            }

    phase1 = _atomic_phase(upsert_key)

    if phase1['response'] is not None:
        return phase1['response']

    key_id = phase1['key_id']
    recovery_point = phase1['recovery_point']

    try:
        while recovery_point != RECOVERY_POINT_FINISHED:
            if recovery_point == RECOVERY_POINT_STARTED:
                recovery_point = _phase_create_ride(
                    key_id, user_id, request_params
                )
                if simulate_crash_at == RECOVERY_POINT_RIDE_CREATED:
                    _unlock_key(key_id)
                    raise CrashSimulation(
                        f"Simulated crash at {RECOVERY_POINT_RIDE_CREATED}"
                    )

            elif recovery_point == RECOVERY_POINT_RIDE_CREATED:
                recovery_point = _phase_create_charge(key_id, user_id)
                if simulate_crash_at == RECOVERY_POINT_CHARGE_CREATED:
                    _unlock_key(key_id)
                    raise CrashSimulation(
                        f"Simulated crash at {RECOVERY_POINT_CHARGE_CREATED}"
                    )

            elif recovery_point == RECOVERY_POINT_CHARGE_CREATED:
                return _phase_finish(key_id, user_id)

            else:
                raise RuntimeError(
                    f"Bug! Unknown recovery point: {recovery_point}"
                )

    except (CrashSimulation, ParameterMismatch, IdempotencyConflict):
        raise
    except Exception:
        _unlock_key(key_id)
        raise


def _phase_create_ride(key_id, user_id, request_params):
    """Phase 2: Create ride + audit record. Sets recovery_point to 'ride_created'."""
    def execute(cur):
        cur.execute(
            "INSERT INTO rides "
            "  (idempotency_key_id, origin_lat, origin_lon, "
            "   target_lat, target_lon, user_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (key_id,
             request_params['origin_lat'], request_params['origin_lon'],
             request_params['target_lat'], request_params['target_lon'],
             user_id)
        )
        ride_id = cur.fetchone()['id']

        cur.execute(
            "INSERT INTO audit_records "
            "  (action, data, resource_id, resource_type, user_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            ('ride_created', psycopg2.extras.Json(request_params),
             ride_id, 'ride', user_id)
        )

        cur.execute(
            "UPDATE idempotency_keys SET recovery_point = %s WHERE id = %s",
            (RECOVERY_POINT_RIDE_CREATED, key_id)
        )

        return RECOVERY_POINT_RIDE_CREATED

    return _atomic_phase(execute)


def _phase_create_charge(key_id, user_id):
    """Phase 3: Create charge. Sets recovery_point to 'charge_created'."""
    def execute(cur):
        cur.execute(
            "SELECT id FROM rides WHERE idempotency_key_id = %s",
            (key_id,)
        )
        ride = cur.fetchone()
        if ride is None:
            raise RuntimeError(
                f"Bug! No ride found for idempotency key {key_id} "
                f"at recovery point {RECOVERY_POINT_RIDE_CREATED}"
            )
        ride_id = ride['id']

        cur.execute(
            "SELECT stripe_customer_id FROM users WHERE id = %s",
            (user_id,)
        )
        customer_id = cur.fetchone()['stripe_customer_id']

        charge_id = f"ch_{uuid.uuid4().hex[:24]}"

        cur.execute(
            "INSERT INTO charges (id, amount, currency, customer_id, description) "
            "VALUES (%s, %s, %s, %s, %s)",
            (charge_id, 2000, 'usd', customer_id,
             f"Charge for ride {ride_id}")
        )

        cur.execute(
            "UPDATE rides SET stripe_charge_id = %s WHERE id = %s",
            (charge_id, ride_id)
        )

        cur.execute(
            "UPDATE idempotency_keys SET recovery_point = %s WHERE id = %s",
            (RECOVERY_POINT_CHARGE_CREATED, key_id)
        )

        return RECOVERY_POINT_CHARGE_CREATED

    return _atomic_phase(execute)


def _phase_finish(key_id, user_id):
    """Phase 4: Stage receipt job, store response, mark as finished."""
    def execute(cur):
        cur.execute(
            "SELECT r.id AS ride_id, r.stripe_charge_id "
            "FROM rides r WHERE r.idempotency_key_id = %s",
            (key_id,)
        )
        ride = cur.fetchone()

        cur.execute(
            "INSERT INTO staged_jobs (job_name, job_args) "
            "VALUES (%s, %s)",
            ('send_ride_receipt', psycopg2.extras.Json({
                'amount': 2000,
                'currency': 'usd',
                'user_id': user_id,
                'ride_id': ride['ride_id'],
            }))
        )

        response_body = {
            'ride_id': ride['ride_id'],
            'charge_id': ride['stripe_charge_id'],
        }

        cur.execute(
            "UPDATE idempotency_keys "
            "SET recovery_point = %s, "
            "    locked_at = NULL, "
            "    response_code = %s, "
            "    response_body = %s "
            "WHERE id = %s",
            (RECOVERY_POINT_FINISHED, 201,
             psycopg2.extras.Json(response_body), key_id)
        )

        return {'status_code': 201, 'body': response_body}

    return _atomic_phase(execute)


def complete_stale_requests(staleness_threshold_seconds=300):
    """
    Find and complete requests that appear stale/abandoned.

    Queries for non-finished idempotency keys whose last_run_at and locked_at
    are older than the threshold, then pushes each to completion through the
    normal state machine.
    """
    conn = get_connection()
    conn.autocommit = True
    stale_keys = []

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, user_id, idempotency_key, request_params "
            "FROM idempotency_keys "
            "WHERE recovery_point != %s "
            "  AND last_run_at < now() - make_interval(secs => %s) "
            "  AND (locked_at IS NULL "
            "       OR locked_at < now() - make_interval(secs => %s))",
            (RECOVERY_POINT_FINISHED, staleness_threshold_seconds,
             staleness_threshold_seconds)
        )
        stale_keys = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    completed = 0
    for key in stale_keys:
        try:
            result = process_ride_request(
                user_id=key['user_id'],
                idempotency_key=key['idempotency_key'],
                request_params=key['request_params'],
            )
            if result and result.get('status_code') == 201:
                completed += 1
        except Exception:
            pass

    return completed


def reap_old_keys(age_threshold_hours=72):
    """
    Delete finished idempotency keys older than the threshold.

    Only deletes keys with recovery_point='finished'. The rides table's
    foreign key uses ON DELETE SET NULL, so ride records are preserved
    with their idempotency_key_id set to NULL.
    """
    conn = get_connection()
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM idempotency_keys "
            "WHERE recovery_point = %s "
            "  AND created_at < now() - make_interval(hours => %s)",
            (RECOVERY_POINT_FINISHED, age_threshold_hours)
        )
        reaped = cur.rowcount
        cur.close()
        return reaped
    finally:
        conn.close()
