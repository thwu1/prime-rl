<?php

/**
 * TemplateEngine - simple template renderer with variable substitution.
 * Loads templates from a directory and replaces {{variable}} placeholders.
 */
class TemplateEngine {
    private $templateDir;
    private $cache;
    private $variables = [];

    function __construct($templateDir = '/var/www/html/templates') {
        $this->templateDir = $templateDir;
        $this->cache = new CacheManager('/tmp/template_cache.json');
    }

    function assign($key, $value) {
        $this->variables[$key] = $value;
    }

    function assignArray($data) {
        foreach ($data as $key => $value) {
            $this->variables[$key] = $value;
        }
    }

    function render($template) {
        $cached = $this->cache->get($template);
        if ($cached) {
            return $this->interpolate($cached);
        }

        $path = $this->templateDir . '/' . basename($template);
        if (!file_exists($path)) {
            return "<!-- Template not found: " . htmlspecialchars($template) . " -->";
        }
        $content = file_get_contents($path);
        $this->cache->set($template, $content);
        return $this->interpolate($content);
    }

    private function interpolate($content) {
        foreach ($this->variables as $k => $v) {
            $content = str_replace('{{' . $k . '}}', htmlspecialchars((string)$v), $content);
        }
        return $content;
    }
}
