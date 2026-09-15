<?php

class UserPreferences {
    public $theme = 'light';
    public $language = 'en';
    public $notifications = true;
    public $timezone = 'UTC';

    function apply() {
        date_default_timezone_set($this->timezone);
    }

    function toArray() {
        return [
            'theme' => $this->theme,
            'language' => $this->language,
            'notifications' => $this->notifications,
            'timezone' => $this->timezone,
        ];
    }
}
