<?php

class SimpleFormat {
    private $template = '[%s] [%s] %s';

    function render($message, $level, $dateFormat) {
        return sprintf($this->template, date($dateFormat), strtoupper($level), $message);
    }

    function renderBatch($messages, $level, $dateFormat) {
        $output = '';
        foreach ($messages as $msg) {
            $output .= $this->render($msg, $level, $dateFormat) . "\n";
        }
        return $output;
    }
}
