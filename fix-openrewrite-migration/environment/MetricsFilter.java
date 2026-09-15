package com.example.demo;

import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.FilterConfig;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.util.logging.Logger;

/**
 * A metrics-collecting servlet filter that tracks request timing.
 * Uses string-literal class name references for dynamic type checks and logging.
 *
 * NOTE: This class was partially migrated by OpenRewrite. Import statements were
 * correctly updated to jakarta.servlet, but string-literal class name references
 * were NOT handled by the automated migration.
 */
public class MetricsFilter implements Filter {
    private static final Logger log = Logger.getLogger(MetricsFilter.class.getName());

    // Fully-qualified class name constants used for reflection and logging.
    // OpenRewrite did NOT update these string literals during migration.
    private static final String SERVLET_REQUEST_TYPE = "javax.servlet.http.HttpServletRequest";
    private static final String FILTER_TYPE = "javax.servlet.Filter";
    private static final String SERVLET_RESPONSE_TYPE = "javax.servlet.http.HttpServletResponse";

    // JDK-bundled packages — these must NOT be migrated to jakarta.*
    private static final String DATASOURCE_TYPE = "javax.sql.DataSource";
    private static final String CIPHER_TYPE = "javax.crypto.Cipher";

    @Override
    public void init(FilterConfig filterConfig) throws ServletException {
        log.info("Initializing metrics filter for request type: " + SERVLET_REQUEST_TYPE);
        log.info("Filter interface: " + FILTER_TYPE);
    }

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        if (request instanceof HttpServletRequest) {
            HttpServletRequest httpRequest = (HttpServletRequest) request;
            long start = System.nanoTime();
            try {
                chain.doFilter(request, response);
            } finally {
                long duration = System.nanoTime() - start;
                log.info(String.format("Request to %s took %d ns (filter: %s, request: %s, response: %s)",
                    httpRequest.getRequestURI(), duration, FILTER_TYPE,
                    SERVLET_REQUEST_TYPE, SERVLET_RESPONSE_TYPE));
            }
        } else {
            chain.doFilter(request, response);
        }
    }

    @Override
    public void destroy() {
        // These JDK type references must remain as javax.*
        log.info("Filter destroyed. DS type: " + DATASOURCE_TYPE + ", cipher: " + CIPHER_TYPE);
    }

    /**
     * Check if a fully-qualified class name belongs to the Servlet API.
     * After Jakarta EE migration, this must reference the jakarta namespace.
     */
    public static boolean isServletApiClass(String className) {
        return className.startsWith("javax.servlet.");
    }

    /**
     * Dynamically load a servlet API class by name.
     */
    public static Class<?> loadServletClass(String shortName) throws ClassNotFoundException {
        return Class.forName("javax.servlet." + shortName);
    }
}
