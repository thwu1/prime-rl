<?php

/**
 * DataMapper - applies a transformation callback to data.
 * Supports both direct invocation and dynamic method dispatch.
 */
class DataMapper {
    private $callback;
    private $options;

    function __construct($callback, $options = []) {
        $this->callback = $callback;
        $this->options = $options;
    }

    function transform($data) {
        return call_user_func($this->callback, $data);
    }

    function transformBatch($items) {
        $results = [];
        foreach ($items as $item) {
            $results[] = $this->transform($item);
        }
        return $results;
    }

    function __call($name, $args) {
        return call_user_func_array($this->callback, $args);
    }

    function getCallback() {
        return $this->callback;
    }
}
