<?php

class UserSession {
    public $username;
    public $role;
    public $preferences;
    public $last_login;

    function __construct($username, $role = 'user') {
        $this->username = $username;
        $this->role = $role;
        $this->preferences = new UserPreferences();
        $this->last_login = date('Y-m-d H:i:s');
    }

    function __sleep() {
        return ['username', 'role', 'preferences', 'last_login'];
    }

    function __wakeup() {
        if ($this->preferences === null) {
            $this->preferences = new UserPreferences();
        }
    }

    function isAdmin() {
        return $this->role === 'admin';
    }
}
