Oracle 19c Performance Incident Data Export
==========================================

Database: ECOM_PROD (Oracle 19c Enterprise Edition)
Instance: ecom1
Platform: Oracle Linux 8.x
Export Time: 2024-06-15 14:30 UTC (during peak load incident)

This directory contains performance data exported from the production database
during a severe performance degradation incident. The application is an
e-commerce OLTP system serving web and mobile clients.

Incident Description:
- Application response times increased 5x during peak hours (12:00-15:00 UTC)
- Users reported timeouts on order placement and order lookup pages
- Database CPU utilization at 95%, with significant I/O wait
- The database has been running for 7 days since last restart

Files (Oracle SQL*Plus spool output format):
- sysstat.lst: System-wide statistics (V$SYSSTAT)
- system_event.lst: Wait event statistics (V$SYSTEM_EVENT)
- db_cache_advice.lst: Buffer cache sizing advisory (V$DB_CACHE_ADVICE)
- librarycache.lst: Library cache statistics (V$LIBRARYCACHE)
- pgastat.lst: PGA memory statistics (V$PGASTAT)
- pga_target_advice.lst: PGA sizing advisory (V$PGA_TARGET_ADVICE)
- sqlarea.lst: Top SQL statements by resource usage (V$SQLAREA)
- parameter.lst: Database initialization parameters (V$PARAMETER subset)
- sgastat.lst: SGA component sizes (V$SGASTAT)
- waitstat.lst: Buffer wait statistics by block class (V$WAITSTAT)
- execution_plans.lst: DBMS_XPLAN output for top SQL
- schema_info.txt: Table and index definitions for referenced objects

All memory values are in bytes unless otherwise noted.
All time values are in microseconds unless otherwise noted.
