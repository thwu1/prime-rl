<?php

/**
 * FileTransport - writes data to a file on disk.
 * Used by Logger for file-based log storage.
 */
class FileTransport {
    private $path;
    private $handle;
    private $mode;

    function __construct($path, $mode = 'a') {
        $this->path = $path;
        $this->mode = $mode;
        $this->handle = null;
    }

    function write($data) {
        if (!$this->handle) {
            $this->handle = @fopen($this->path, $this->mode);
        }
        if ($this->handle) {
            fwrite($this->handle, $data . "\n");
        }
    }

    function close() {
        if ($this->handle) {
            fclose($this->handle);
            $this->handle = null;
        }
    }

    function getPath() {
        return $this->path;
    }
}
