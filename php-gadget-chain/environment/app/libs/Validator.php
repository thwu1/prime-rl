<?php

/**
 * Validator - validates data against a set of regex rules.
 */
class Validator {
    private $rules = [];
    private $errors = [];

    function addRule($field, $pattern, $message = null) {
        $this->rules[$field] = [
            'pattern' => $pattern,
            'message' => $message ?? "Invalid value for field: $field",
        ];
    }

    function validate($data) {
        $this->errors = [];
        foreach ($this->rules as $field => $rule) {
            $value = $data[$field] ?? null;
            if ($value === null || !preg_match($rule['pattern'], $value)) {
                $this->errors[$field] = $rule['message'];
            }
        }
        return empty($this->errors);
    }

    function getErrors() {
        return $this->errors;
    }

    function hasErrors() {
        return !empty($this->errors);
    }
}
