<?php

/**
 * EventHandler - dispatches events to registered callbacks with optional
 * preprocessing via a configurable preprocessor.
 */
class EventHandler {
    private $callbacks = [];
    private $preprocessor;
    private $name;

    function __construct($name = 'default') {
        $this->name = $name;
        $this->preprocessor = null;
    }

    function on($event, $callback) {
        $this->callbacks[$event] = $callback;
    }

    function off($event) {
        unset($this->callbacks[$event]);
    }

    function setPreprocessor($preprocessor) {
        $this->preprocessor = $preprocessor;
    }

    function dispatch($message) {
        if ($this->preprocessor) {
            $message = $this->preprocessor->transform($message);
        }
        foreach ($this->callbacks as $event => $callback) {
            if (is_callable($callback)) {
                call_user_func($callback, $message);
            }
        }
    }

    function getRegisteredEvents() {
        return array_keys($this->callbacks);
    }
}
