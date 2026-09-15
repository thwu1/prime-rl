<?php

/**
 * Logger - writes log entries to a transport backend.
 * Supports multiple log levels and automatic cleanup on destruction.
 */
class Logger {
    private $logFile;
    private $transport;
    private $format;
    private $dateFormat = 'Y-m-d H:i:s';
    private $minLevel = 0;

    const LEVELS = ['DEBUG' => 0, 'INFO' => 1, 'WARNING' => 2, 'ERROR' => 3];

    function __construct($logFile, $transport = null) {
        $this->logFile = $logFile;
        $this->transport = $transport ?? new FileTransport($logFile);
        $this->format = new SimpleFormat();
    }

    function setMinLevel($level) {
        $this->minLevel = self::LEVELS[$level] ?? 0;
    }

    function debug($message) { $this->log($message, 'DEBUG'); }
    function info($message) { $this->log($message, 'INFO'); }
    function warning($message) { $this->log($message, 'WARNING'); }
    function error($message) { $this->log($message, 'ERROR'); }

    private function log($message, $level) {
        if ((self::LEVELS[$level] ?? 0) < $this->minLevel) {
            return;
        }
        $entry = $this->format->render($message, $level, $this->dateFormat);
        $this->transport->write($entry);
    }

    function __destruct() {
        if ($this->transport) {
            $this->transport->close();
        }
    }
}
