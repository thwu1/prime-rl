-- Repository packages (available versions)
INSERT INTO repo_packages VALUES ('sys-libs', 'zlib', '1.3', '0', '1.3', '');
INSERT INTO repo_packages VALUES ('sys-libs', 'zlib', '1.3a', '0', '1.3a', '');
INSERT INTO repo_packages VALUES ('dev-libs', 'openssl', '1.1.1w', '0', '1.1', 'sys-libs/zlib:0=');
INSERT INTO repo_packages VALUES ('dev-libs', 'openssl', '3.2.0', '0', '3', 'sys-libs/zlib:0=');
INSERT INTO repo_packages VALUES ('dev-libs', 'icu', '73.2', '0', '73', '');
INSERT INTO repo_packages VALUES ('dev-libs', 'icu', '74.1', '0', '74', '');
INSERT INTO repo_packages VALUES ('dev-libs', 'boost', '1.83.0', '0', '1.83', 'dev-libs/icu:0=');
INSERT INTO repo_packages VALUES ('dev-libs', 'boost', '1.84.0', '0', '1.84', 'dev-libs/icu:0=');
INSERT INTO repo_packages VALUES ('net-misc', 'curl', '8.4.0', '0', '4', 'ssl? ( dev-libs/openssl:0= ) sys-libs/zlib:0=');
INSERT INTO repo_packages VALUES ('net-misc', 'curl', '8.5.0', '0', '4', 'ssl? ( dev-libs/openssl:0= ) sys-libs/zlib:0=');
INSERT INTO repo_packages VALUES ('dev-libs', 'expat', '2.5.0', '0', '0', '');
INSERT INTO repo_packages VALUES ('dev-libs', 'expat', '2.6.0', '0', '0', '');
INSERT INTO repo_packages VALUES ('dev-libs', 'libxml2', '2.12.0', '2', '2', 'sys-libs/zlib');
INSERT INTO repo_packages VALUES ('dev-libs', 'crypto', '1.0', '0', '0', 'dev-libs/icu');
INSERT INTO repo_packages VALUES ('dev-libs', 'crypto', '2.0', '0', '0', 'dev-libs/nonexistent');
INSERT INTO repo_packages VALUES ('dev-libs', 'render', '1.0', '0', '0', 'media-libs/codec:0=');
INSERT INTO repo_packages VALUES ('media-libs', 'codec', '2.0', '0', '2', '');
INSERT INTO repo_packages VALUES ('media-libs', 'codec', '2.1', '0', '2', '');
INSERT INTO repo_packages VALUES ('media-libs', 'codec', '3.0', '0', '3', '');
INSERT INTO repo_packages VALUES ('app-misc', 'viewer', '1.0', '0', '0', 'dev-libs/render:0=');
INSERT INTO repo_packages VALUES ('app-misc', 'client', '1.0', '0', '0', '!minimal? ( dev-libs/expat ) xml? ( dev-libs/libxml2 ) ssl? ( dev-libs/openssl )');
INSERT INTO repo_packages VALUES ('app-misc', 'analyzer', '1.0', '0', '0', '<sys-libs/zlib-1.3a');
INSERT INTO repo_packages VALUES ('app-misc', 'secure', '1.0', '0', '0', 'dev-libs/crypto');

-- Installed packages (current system state)
INSERT INTO installed_packages VALUES ('sys-libs', 'zlib', '1.3', '0', '1.3', '');
INSERT INTO installed_packages VALUES ('dev-libs', 'openssl', '1.1.1w', '0', '1.1', '');
INSERT INTO installed_packages VALUES ('dev-libs', 'icu', '73.2', '0', '73', '');
INSERT INTO installed_packages VALUES ('dev-libs', 'boost', '1.83.0', '0', '1.83', '');
INSERT INTO installed_packages VALUES ('net-misc', 'curl', '8.4.0', '0', '4', 'ssl');
INSERT INTO installed_packages VALUES ('dev-libs', 'expat', '2.5.0', '0', '0', '');
INSERT INTO installed_packages VALUES ('dev-libs', 'libxml2', '2.12.0', '2', '2', '');
INSERT INTO installed_packages VALUES ('media-libs', 'codec', '2.0', '0', '2', '');
INSERT INTO installed_packages VALUES ('dev-libs', 'render', '1.0', '0', '0', '');
INSERT INTO installed_packages VALUES ('app-misc', 'viewer', '1.0', '0', '0', '');
INSERT INTO installed_packages VALUES ('app-misc', 'client', '1.0', '0', '0', 'xml');
