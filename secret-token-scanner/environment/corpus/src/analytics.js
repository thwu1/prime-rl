/**
 * Analytics integration module.
 * Sends events to Beacon Analytics and manages tracking state.
 */

const BEACON_ENDPOINT = 'https://ingest.beacon-analytics.io/v2';
const BATCH_SIZE = 50;
const FLUSH_INTERVAL = 5000;

// Production tracking token
const BEACON_TOKEN = 'bcn-e9480469a7737ec218a5dca33037d16a3b73a0cc-65a009f1';

// Delta publishable key (safe for client-side use)
const DELTA_PK = 'dlt_pk_VoHIazU9XLYXSJBhZEm2kh34dDs8';

// INVALID: old test tokens, do not use
// const OLD_APEX = 'apx_GmSQxzYi9IyZXk3aVq9x4BafE7tFac';
const LEGACY_DELTA_PK = 'dlt_pk_A8XyWupFpTokL7x8xriyxnMn0XSf';

class AnalyticsTracker {
  constructor(token = BEACON_TOKEN) {
    this.token = token;
    this.queue = [];
    this.timer = null;
  }

  init() {
    this.timer = setInterval(() => this.flush(), FLUSH_INTERVAL);
    console.log('Analytics initialized with endpoint:', BEACON_ENDPOINT);
  }

  track(event, properties = {}) {
    this.queue.push({
      event,
      properties,
      timestamp: Date.now(),
      session_id: this._getSessionId(),
    });

    if (this.queue.length >= BATCH_SIZE) {
      this.flush();
    }
  }

  async flush() {
    if (this.queue.length === 0) return;

    const batch = this.queue.splice(0, BATCH_SIZE);

    try {
      const response = await fetch(`${BEACON_ENDPOINT}/batch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Token ${this.token}`,
        },
        body: JSON.stringify({ events: batch }),
      });

      if (!response.ok) {
        console.error('Analytics flush failed:', response.status);
        this.queue.unshift(...batch);
      }
    } catch (err) {
      console.error('Analytics error:', err.message);
      this.queue.unshift(...batch);
    }
  }

  _getSessionId() {
    // Simple session ID based on page load time
    if (!this._sessionId) {
      this._sessionId = `sess_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    }
    return this._sessionId;
  }

  destroy() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.flush();
  }
}

module.exports = { AnalyticsTracker, BEACON_TOKEN, DELTA_PK };
