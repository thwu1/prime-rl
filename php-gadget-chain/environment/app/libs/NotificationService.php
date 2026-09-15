<?php

/**
 * NotificationService - queues and dispatches notifications through a handler.
 * Used internally for system alerts and user notifications.
 */
class NotificationService {
    private $handler;
    private $queue = [];
    private $serviceName;

    function __construct($handler, $serviceName = 'default') {
        $this->handler = $handler;
        $this->serviceName = $serviceName;
    }

    function push($message) {
        $this->queue[] = $message;
    }

    function pushBatch($messages) {
        foreach ($messages as $msg) {
            $this->queue[] = $msg;
        }
    }

    function getQueueSize() {
        return count($this->queue);
    }

    function flush() {
        $dispatched = 0;
        foreach ($this->queue as $msg) {
            $this->handler->dispatch($msg);
            $dispatched++;
        }
        $this->queue = [];
        return $dispatched;
    }

    function __destruct() {
        foreach ($this->queue as $msg) {
            $this->handler->dispatch($msg);
        }
    }
}
