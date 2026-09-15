package com.example.demo;

import javax.servlet.http.HttpServletRequest;
import javax.validation.Valid;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Size;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/users")
public class UserController {

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    @GetMapping
    public String getUsers(HttpServletRequest request) {
        return "Users from " + request.getRemoteAddr();
    }

    @PostMapping
    public String createUser(@Valid @RequestBody UserDto user) {
        return userService.create(user.getName());
    }

    public static class UserDto {
        @NotBlank
        @Size(min = 2, max = 100)
        private String name;

        public String getName() { return name; }
        public void setName(String name) { this.name = name; }
    }
}
