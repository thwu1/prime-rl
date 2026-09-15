package com.example.demo;

import jakarta.sql.DataSource;
import javax.annotation.PostConstruct;
import org.springframework.context.annotation.Configuration;
import java.util.logging.Logger;

/**
 * Cache configuration that references database types.
 */
@Configuration
public class CacheConfig {

    private static final Logger log = Logger.getLogger(CacheConfig.class.getName());

    private static final String DS_TYPE = "jakarta.sql.DataSource";

    @PostConstruct
    public void init() {
        log.info("Cache config initialized, expected datasource type: " + DS_TYPE);
    }

    public void configureCache(DataSource dataSource) {
        log.info("Configuring cache with: " + dataSource.getClass().getName());
    }
}
