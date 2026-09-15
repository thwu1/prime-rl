package com.example.demo;

import org.springframework.stereotype.Service;

@Service
public class UserService {
    public String create(String name) {
        return "Created user: " + name;
    }
}
