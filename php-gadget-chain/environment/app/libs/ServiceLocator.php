<?php

/**
 * ServiceLocator - registry for named services with dynamic dispatch.
 * Allows retrieval and invocation of registered service callbacks.
 */
class ServiceLocator {
    private $services = [];
    private $initialized = [];

    function register($name, $service) {
        $this->services[$name] = $service;
        $this->initialized[$name] = false;
    }

    function get($name) {
        if (!isset($this->services[$name])) {
            throw new \RuntimeException("Service not found: $name");
        }
        if (!$this->initialized[$name] && is_callable($this->services[$name])) {
            $this->services[$name] = call_user_func($this->services[$name]);
            $this->initialized[$name] = true;
        }
        return $this->services[$name];
    }

    function has($name) {
        return isset($this->services[$name]);
    }

    function getNames() {
        return array_keys($this->services);
    }

    function __call($name, $args) {
        if (isset($this->services[$name])) {
            if (is_callable($this->services[$name])) {
                return call_user_func_array($this->services[$name], $args);
            }
            return $this->services[$name];
        }
        throw new \RuntimeException("Service not found: $name");
    }
}
