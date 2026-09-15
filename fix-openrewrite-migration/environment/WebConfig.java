package com.example.demo;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurerAdapter;
import org.springframework.web.servlet.HandlerInterceptor;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.util.logging.Logger;

/**
 * Web MVC configuration for request interceptors.
 */
@Configuration
public class WebConfig extends WebMvcConfigurerAdapter {

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new RequestLoggingInterceptor());
    }

    static class RequestLoggingInterceptor implements HandlerInterceptor {
        private static final Logger log = Logger.getLogger(RequestLoggingInterceptor.class.getName());

        @Override
        public boolean preHandle(HttpServletRequest request, HttpServletResponse response,
                                 Object handler) {
            log.info("Incoming: " + request.getMethod() + " " + request.getRequestURI());
            return true;
        }
    }
}
