-- Package database schema for Portage-style resolver
-- repo_packages: available versions in the ebuild repository
-- installed_packages: currently installed versions with USE state

CREATE TABLE repo_packages (
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    slot TEXT NOT NULL DEFAULT '0',
    subslot TEXT NOT NULL DEFAULT '0',
    rdepend TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (category, name, version)
);

CREATE TABLE installed_packages (
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    slot TEXT NOT NULL DEFAULT '0',
    subslot TEXT NOT NULL DEFAULT '0',
    use_flags TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (category, name, version)
);
