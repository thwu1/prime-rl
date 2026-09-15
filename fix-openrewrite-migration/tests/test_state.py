
"""
Verify a partially-and-incorrectly migrated Spring Boot 3.0 application
has been correctly repaired across all dimensions: compilation, imports,
removed API replacements, namespace correctness, string literals, dynamic
class loading, dependency management, and configuration properties.
"""

import os
import re
import subprocess
import pytest


def read_file(path):
    with open(path, "r") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Compilation — the project must compile cleanly with Spring Boot 3.0
# ---------------------------------------------------------------------------

class TestCompilation:
    def test_mvn_compile_succeeds(self):
        """The project must compile cleanly under Spring Boot 3.0.13"""
        result = subprocess.run(
            ["mvn", "compile", "-q", "-B"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=180
        )
        assert result.returncode == 0, (
            f"mvn compile failed (exit {result.returncode}):\n"
            f"{result.stderr[-3000:]}"
        )


# ---------------------------------------------------------------------------
# pom.xml — dependency hygiene
# ---------------------------------------------------------------------------

class TestPomXml:
    @pytest.fixture(autouse=True)
    def load_pom(self):
        self.pom = read_file("/app/pom.xml")

    def test_no_javax_annotation_api_workaround(self):
        """The javax.annotation-api workaround dependency must be removed"""
        assert "javax.annotation-api" not in self.pom, (
            "pom.xml still contains javax.annotation-api workaround dependency"
        )

    def test_no_javax_annotation_group(self):
        """No javax.annotation groupId should remain in dependencies"""
        assert "<groupId>javax.annotation</groupId>" not in self.pom, (
            "pom.xml still has javax.annotation groupId"
        )

    def test_has_jaxb_api_dependency(self):
        """jakarta.xml.bind-api dependency must be present for JAXB support"""
        assert "jakarta.xml.bind-api" in self.pom, (
            "pom.xml missing jakarta.xml.bind-api dependency for JAXB"
        )


# ---------------------------------------------------------------------------
# DemoApplication.java — javax.annotation must be migrated
# ---------------------------------------------------------------------------

class TestDemoApplication:
    @pytest.fixture(autouse=True)
    def load_source(self):
        self.src = read_file(
            "/app/src/main/java/com/example/demo/DemoApplication.java"
        )

    def test_no_javax_annotation(self):
        """javax.annotation imports must be migrated to jakarta.annotation"""
        assert "import javax.annotation" not in self.src, (
            "DemoApplication.java still has javax.annotation import"
        )

    def test_has_jakarta_annotation(self):
        """Should have jakarta.annotation import for @PostConstruct"""
        assert "jakarta.annotation" in self.src, (
            "DemoApplication.java missing jakarta.annotation import"
        )

    def test_postconstruct_still_present(self):
        """@PostConstruct annotation must still be used"""
        assert "@PostConstruct" in self.src, (
            "DemoApplication.java missing @PostConstruct annotation"
        )


# ---------------------------------------------------------------------------
# UserController.java — javax.servlet and javax.validation must be migrated
# ---------------------------------------------------------------------------

class TestUserController:
    @pytest.fixture(autouse=True)
    def load_source(self):
        self.src = read_file(
            "/app/src/main/java/com/example/demo/UserController.java"
        )

    def test_no_javax_validation(self):
        """javax.validation imports must be migrated to jakarta.validation"""
        assert "import javax.validation" not in self.src, (
            "UserController.java still has javax.validation import"
        )

    def test_has_jakarta_validation(self):
        """Should have jakarta.validation imports"""
        assert "jakarta.validation" in self.src, (
            "UserController.java missing jakarta.validation import"
        )

    def test_no_javax_servlet(self):
        """javax.servlet imports must be migrated to jakarta.servlet"""
        assert "import javax.servlet" not in self.src, (
            "UserController.java still has javax.servlet import"
        )

    def test_has_jakarta_servlet(self):
        """Should have jakarta.servlet imports"""
        assert "jakarta.servlet" in self.src, (
            "UserController.java missing jakarta.servlet import"
        )

    def test_valid_annotation_present(self):
        """@Valid annotation must still be used"""
        assert "@Valid" in self.src

    def test_notblank_annotation_present(self):
        """@NotBlank annotation must still be used"""
        assert "@NotBlank" in self.src


# ---------------------------------------------------------------------------
# SecurityConfig.java — WebSecurityConfigurerAdapter migration
# ---------------------------------------------------------------------------

class TestSecurityConfig:
    @pytest.fixture(autouse=True)
    def load_source(self):
        self.src = read_file(
            "/app/src/main/java/com/example/demo/SecurityConfig.java"
        )

    def test_no_web_security_configurer_adapter(self):
        """WebSecurityConfigurerAdapter was removed in Spring Security 6.0"""
        assert "WebSecurityConfigurerAdapter" not in self.src, (
            "SecurityConfig.java still references removed WebSecurityConfigurerAdapter"
        )

    def test_has_security_filter_chain(self):
        """Must use SecurityFilterChain bean pattern"""
        assert "SecurityFilterChain" in self.src, (
            "SecurityConfig.java missing SecurityFilterChain return type"
        )

    def test_has_bean_annotation(self):
        """SecurityFilterChain method must be annotated with @Bean"""
        assert "@Bean" in self.src, (
            "SecurityConfig.java missing @Bean annotation on filter chain method"
        )

    def test_uses_authorize_http_requests(self):
        """Must use authorizeHttpRequests (not deprecated authorizeRequests)"""
        assert "authorizeHttpRequests" in self.src, (
            "SecurityConfig.java not using authorizeHttpRequests"
        )

    def test_uses_request_matchers(self):
        """Must use requestMatchers (antMatchers was removed in Security 6.0)"""
        assert "requestMatchers" in self.src, (
            "SecurityConfig.java not using requestMatchers"
        )

    def test_no_ant_matchers(self):
        """antMatchers was removed in Spring Security 6.0"""
        assert "antMatchers" not in self.src, (
            "SecurityConfig.java still references removed antMatchers"
        )

    def test_returns_built_chain(self):
        """Must call http.build() to produce SecurityFilterChain"""
        assert ".build()" in self.src, (
            "SecurityConfig.java not calling .build() on HttpSecurity"
        )

    def test_preserves_public_endpoint(self):
        """The /api/public/** permit rule must be preserved"""
        assert "/api/public/**" in self.src, (
            "SecurityConfig.java lost the /api/public/** permit rule"
        )

    def test_preserves_health_endpoint(self):
        """The /actuator/health permit rule must be preserved"""
        assert "/actuator/health" in self.src, (
            "SecurityConfig.java lost the /actuator/health permit rule"
        )


# ---------------------------------------------------------------------------
# WebConfig.java — WebMvcConfigurerAdapter migration
# ---------------------------------------------------------------------------

class TestWebConfig:
    @pytest.fixture(autouse=True)
    def load_source(self):
        self.src = read_file(
            "/app/src/main/java/com/example/demo/WebConfig.java"
        )

    def test_no_web_mvc_configurer_adapter(self):
        """WebMvcConfigurerAdapter was removed in Spring Framework 6.0"""
        assert "WebMvcConfigurerAdapter" not in self.src, (
            "WebConfig.java still references removed WebMvcConfigurerAdapter"
        )

    def test_implements_web_mvc_configurer(self):
        """Must implement WebMvcConfigurer directly"""
        assert "WebMvcConfigurer" in self.src, (
            "WebConfig.java missing WebMvcConfigurer"
        )

    def test_add_interceptors_preserved(self):
        """addInterceptors method must still be present"""
        assert "addInterceptors" in self.src, (
            "WebConfig.java lost addInterceptors method"
        )

    def test_handler_interceptor_preserved(self):
        """HandlerInterceptor implementation must still be present"""
        assert "HandlerInterceptor" in self.src, (
            "WebConfig.java lost HandlerInterceptor"
        )


# ---------------------------------------------------------------------------
# CacheConfig.java — over-migration reversal + forward migration
# ---------------------------------------------------------------------------

class TestCacheConfig:
    @pytest.fixture(autouse=True)
    def load_source(self):
        self.src = read_file(
            "/app/src/main/java/com/example/demo/CacheConfig.java"
        )

    def test_uses_javax_sql_import(self):
        """javax.sql.DataSource is a JDK class — import must use javax, not jakarta"""
        assert "import javax.sql.DataSource" in self.src, (
            "CacheConfig.java must import javax.sql.DataSource (JDK package)"
        )

    def test_no_jakarta_sql(self):
        """jakarta.sql does not exist — any jakarta.sql reference is incorrect"""
        assert "jakarta.sql" not in self.src, (
            "CacheConfig.java has incorrect jakarta.sql reference (javax.sql is JDK)"
        )

    def test_has_jakarta_annotation(self):
        """PostConstruct should use jakarta.annotation after migration"""
        assert "import jakarta.annotation" in self.src, (
            "CacheConfig.java missing jakarta.annotation import"
        )

    def test_no_javax_annotation_import(self):
        """javax.annotation should not remain after proper migration"""
        assert "import javax.annotation" not in self.src, (
            "CacheConfig.java still has javax.annotation import"
        )

    def test_postconstruct_present(self):
        """@PostConstruct annotation must be preserved"""
        assert "@PostConstruct" in self.src, (
            "CacheConfig.java lost @PostConstruct annotation"
        )

    def test_string_literal_uses_javax_sql(self):
        """String literal DS_TYPE must reference javax.sql, not jakarta.sql"""
        assert '"javax.sql.DataSource"' in self.src, (
            "CacheConfig.java string literal should use javax.sql.DataSource"
        )


# ---------------------------------------------------------------------------
# DataExporter.java — JAXB migration (javax.xml.bind → jakarta.xml.bind)
# ---------------------------------------------------------------------------

class TestDataExporter:
    @pytest.fixture(autouse=True)
    def load_source(self):
        self.src = read_file(
            "/app/src/main/java/com/example/demo/DataExporter.java"
        )

    def test_has_jakarta_xml_bind(self):
        """JAXB imports must use jakarta.xml.bind namespace"""
        assert "import jakarta.xml.bind" in self.src, (
            "DataExporter.java missing jakarta.xml.bind imports"
        )

    def test_no_javax_xml_bind(self):
        """javax.xml.bind was removed from JDK — must not remain"""
        assert "import javax.xml.bind" not in self.src, (
            "DataExporter.java still has javax.xml.bind imports"
        )

    def test_jaxb_context_present(self):
        """JAXBContext usage must be preserved"""
        assert "JAXBContext" in self.src, (
            "DataExporter.java lost JAXBContext usage"
        )

    def test_xml_root_element_present(self):
        """@XmlRootElement annotation must be preserved"""
        assert "@XmlRootElement" in self.src, (
            "DataExporter.java lost @XmlRootElement annotation"
        )

    def test_xml_element_present(self):
        """@XmlElement annotation must be preserved"""
        assert "@XmlElement" in self.src, (
            "DataExporter.java lost @XmlElement annotation"
        )


# ---------------------------------------------------------------------------
# MetricsFilter.java — selective string literal migration
# ---------------------------------------------------------------------------

class TestMetricsFilter:
    @pytest.fixture(autouse=True)
    def load_source(self):
        self.src = read_file(
            "/app/src/main/java/com/example/demo/MetricsFilter.java"
        )

    def test_imports_still_jakarta(self):
        """Import statements must remain jakarta.servlet (already correct)"""
        assert "import jakarta.servlet" in self.src, (
            "MetricsFilter.java imports should be jakarta.servlet"
        )
        assert "import javax.servlet" not in self.src, (
            "MetricsFilter.java has javax.servlet imports"
        )

    def test_string_literal_servlet_request_migrated(self):
        """String constant SERVLET_REQUEST_TYPE must reference jakarta"""
        assert '"jakarta.servlet.http.HttpServletRequest"' in self.src, (
            "SERVLET_REQUEST_TYPE not migrated to jakarta.servlet"
        )
        assert '"javax.servlet.http.HttpServletRequest"' not in self.src, (
            "SERVLET_REQUEST_TYPE still references javax.servlet"
        )

    def test_string_literal_filter_migrated(self):
        """String constant FILTER_TYPE must reference jakarta"""
        assert '"jakarta.servlet.Filter"' in self.src, (
            "FILTER_TYPE not migrated to jakarta.servlet"
        )
        assert '"javax.servlet.Filter"' not in self.src, (
            "FILTER_TYPE still references javax.servlet"
        )

    def test_string_literal_servlet_response_migrated(self):
        """String constant SERVLET_RESPONSE_TYPE must reference jakarta"""
        assert '"jakarta.servlet.http.HttpServletResponse"' in self.src, (
            "SERVLET_RESPONSE_TYPE not migrated to jakarta.servlet"
        )
        assert '"javax.servlet.http.HttpServletResponse"' not in self.src, (
            "SERVLET_RESPONSE_TYPE still references javax.servlet"
        )

    def test_javax_sql_preserved(self):
        """javax.sql is a JDK package and must NOT be changed"""
        assert '"javax.sql.DataSource"' in self.src, (
            "javax.sql.DataSource was incorrectly migrated — it is a JDK package"
        )

    def test_javax_crypto_preserved(self):
        """javax.crypto is a JDK package and must NOT be changed"""
        assert '"javax.crypto.Cipher"' in self.src, (
            "javax.crypto.Cipher was incorrectly migrated — it is a JDK package"
        )

    def test_starts_with_check_migrated(self):
        """isServletApiClass() must check for jakarta.servlet, not javax.servlet"""
        assert '"jakarta.servlet."' in self.src, (
            "isServletApiClass check not updated to jakarta.servlet."
        )
        assert '"javax.servlet."' not in self.src, (
            "isServletApiClass check still references javax.servlet."
        )

    def test_dynamic_class_loading_migrated(self):
        """Class.forName must use jakarta.servlet namespace for loading"""
        assert 'Class.forName("javax.servlet' not in self.src, (
            "loadServletClass still builds javax.servlet class names dynamically"
        )


# ---------------------------------------------------------------------------
# application.properties — key renames and value migrations
# ---------------------------------------------------------------------------

class TestApplicationProperties:
    @pytest.fixture(autouse=True)
    def load_props(self):
        self.props = read_file(
            "/app/src/main/resources/application.properties"
        )

    def test_header_size_renamed(self):
        """server.max-http-header-size -> server.max-http-request-header-size"""
        assert "server.max-http-request-header-size" in self.props, (
            "Missing renamed property server.max-http-request-header-size"
        )
        lines = [
            l for l in self.props.splitlines()
            if l.strip().startswith("server.max-http-header-size")
            and "request" not in l
        ]
        assert len(lines) == 0, (
            "Old property server.max-http-header-size should be renamed"
        )

    def test_sanitize_key_deleted(self):
        """management.endpoint.configprops.additional-keys-to-sanitize removed"""
        assert "additional-keys-to-sanitize" not in self.props, (
            "Deprecated property additional-keys-to-sanitize should be removed"
        )

    def test_passthrough_preserved(self):
        """spring.jpa.properties.* pass-through properties should be preserved"""
        assert "spring.jpa.properties.hibernate.default_schema" in self.props, (
            "Pass-through property should not be modified"
        )

    def test_custom_filter_class_migrated(self):
        """app.metrics.filter-class value must use jakarta.servlet"""
        assert "app.metrics.filter-class=jakarta.servlet.Filter" in self.props, (
            "Custom property app.metrics.filter-class not migrated to jakarta"
        )

    def test_custom_request_class_migrated(self):
        """app.metrics.request-class value must use jakarta.servlet"""
        assert "app.metrics.request-class=jakarta.servlet.http.HttpServletRequest" \
            in self.props, (
            "Custom property app.metrics.request-class not migrated to jakarta"
        )

    def test_datasource_type_preserved(self):
        """app.datasource.type=javax.sql.DataSource must NOT be changed"""
        assert "app.datasource.type=javax.sql.DataSource" in self.props, (
            "javax.sql.DataSource was incorrectly migrated — it is a JDK package"
        )


# ---------------------------------------------------------------------------
# filter-config.properties — property value migration
# ---------------------------------------------------------------------------

class TestFilterConfigProperties:
    @pytest.fixture(autouse=True)
    def load_props(self):
        self.props = read_file(
            "/app/src/main/resources/filter-config.properties"
        )

    def test_filter_class_migrated(self):
        """filter.audit.class value must be jakarta.servlet.Filter"""
        lines = [l for l in self.props.splitlines()
                 if l.startswith("filter.audit.class=")]
        assert len(lines) == 1
        assert "jakarta.servlet.Filter" in lines[0], (
            f"filter.audit.class not migrated: {lines[0]}"
        )

    def test_request_type_migrated(self):
        """filter.audit.request-type must reference jakarta.servlet"""
        assert "jakarta.servlet.http.HttpServletRequest" in self.props, (
            "filter.audit.request-type not migrated to jakarta.servlet"
        )

    def test_response_type_migrated(self):
        """filter.audit.response-type must reference jakarta.servlet"""
        assert "jakarta.servlet.http.HttpServletResponse" in self.props, (
            "filter.audit.response-type not migrated to jakarta.servlet"
        )

    def test_datasource_class_preserved(self):
        """javax.sql.DataSource is a JDK package and must NOT be changed"""
        assert "javax.sql.DataSource" in self.props, (
            "javax.sql.DataSource was incorrectly migrated in filter-config.properties"
        )

    def test_no_javax_servlet_remaining(self):
        """No javax.servlet references should remain in this file"""
        for line in self.props.splitlines():
            if line.startswith("#"):
                continue
            assert "javax.servlet" not in line, (
                f"javax.servlet still present in non-comment line: {line}"
            )
