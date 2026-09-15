from flask import Flask, jsonify
from redis.sentinel import Sentinel
import json

app = Flask(__name__)

SENTINEL_HOSTS = [('127.0.0.1', 26379), ('127.0.0.1', 26380), ('127.0.0.1', 26381)]
SENTINEL_SERVICE = 'redis-primary'
REDIS_PASSWORD = 'wrongpass'


def get_redis():
    sentinel = Sentinel(SENTINEL_HOSTS, socket_timeout=3)
    return sentinel.master_for(SENTINEL_SERVICE, password=REDIS_PASSWORD,
                               socket_timeout=3, decode_responses=True)


@app.route('/health')
def health():
    try:
        sentinel = Sentinel(SENTINEL_HOSTS, socket_timeout=3)
        master_addr = sentinel.discover_master(SENTINEL_SERVICE)
        client = get_redis()
        client.ping()
        info = client.info('replication')
        return jsonify({
            'status': 'ok',
            'master': f'{master_addr[0]}:{master_addr[1]}',
            'connected_replicas': info.get('connected_slaves', 0)
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/records/count')
def record_count():
    try:
        client = get_redis()
        keys = client.keys('record:*')
        return jsonify({'count': len(keys)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/records/<int:record_id>')
def get_record(record_id):
    try:
        client = get_redis()
        data = client.get(f'record:{record_id}')
        if data is None:
            return jsonify({'error': 'not found'}), 404
        return jsonify(json.loads(data))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
