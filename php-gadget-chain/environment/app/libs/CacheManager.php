<?php

/**
 * CacheManager - in-memory key-value cache with disk persistence.
 * Serializes cache state on destruction for later restoration.
 */
class CacheManager {
    private $store = [];
    private $ttl = 3600;
    private $prefix = 'cache_';
    private $dumpFile;

    function __construct($dumpFile = '/tmp/cache_dump.json') {
        $this->dumpFile = $dumpFile;
    }

    function get($key) {
        $full_key = $this->prefix . $key;
        if (isset($this->store[$full_key])) {
            $entry = $this->store[$full_key];
            if ($entry['expires'] > time()) {
                return $entry['value'];
            }
            unset($this->store[$full_key]);
        }
        return null;
    }

    function set($key, $value, $ttl = null) {
        $this->store[$this->prefix . $key] = [
            'value' => $value,
            'expires' => time() + ($ttl ?? $this->ttl),
        ];
    }

    function delete($key) {
        unset($this->store[$this->prefix . $key]);
    }

    function clear() {
        $this->store = [];
    }

    function __wakeup() {
        if ($this->dumpFile && file_exists($this->dumpFile)) {
            $data = json_decode(file_get_contents($this->dumpFile), true);
            if (is_array($data)) {
                $this->store = $data;
            }
        }
    }

    function __destruct() {
        if (!empty($this->store) && $this->dumpFile) {
            @file_put_contents($this->dumpFile, json_encode($this->store));
        }
    }
}
