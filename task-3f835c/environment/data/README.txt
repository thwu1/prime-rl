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

Files:
- v_sysstat.csv: System-wide statistics (V$SYSSTAT)
- v_system_event.csv: Wait event statistics (V$SYSTEM_EVENT)
- v_db_cache_advice.csv: Buffer cache sizing advisory (V$DB_CACHE_ADVICE)
- v_librarycache.csv: Library cache statistics (V$LIBRARYCACHE)
- v_pgastat.csv: PGA memory statistics (V$PGASTAT)
- v_pga_target_advice.csv: PGA sizing advisory (V$PGA_TARGET_ADVICE)
- v_sqlarea.csv: Top SQL statements by resource usage (V$SQLAREA)
- v_parameter.csv: Database initialization parameters (V$PARAMETER subset)
- v_sgastat.csv: SGA component sizes (V$SGASTAT)
- v_waitstat.csv: Buffer wait statistics by block class (V$WAITSTAT)
- execution_plans.txt: DBMS_XPLAN output for top SQL
- schema_info.txt: Table and index definitions for referenced objects

All memory values are in bytes unless otherwise noted.
All time values are in microseconds unless otherwise noted.
