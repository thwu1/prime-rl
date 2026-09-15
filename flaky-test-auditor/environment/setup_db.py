#!/usr/bin/env python3
"""Generate the IDoFT SQLite database for the reconciliation task."""

import sqlite3
import hashlib
import os

DB_PATH = "/app/idoft.db"


def sha(seed):
    return hashlib.sha1(str(seed).encode()).hexdigest()


def create_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE pr_data (
            id INTEGER PRIMARY KEY,
            project_url TEXT NOT NULL,
            sha_detected TEXT NOT NULL,
            module_path TEXT NOT NULL,
            test_name TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT DEFAULT '',
            pr_link TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE gr_data (
            id INTEGER PRIMARY KEY,
            project_url TEXT NOT NULL,
            sha_detected TEXT NOT NULL,
            module_path TEXT NOT NULL,
            test_name TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT DEFAULT '',
            pr_link TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE py_data (
            id INTEGER PRIMARY KEY,
            project_url TEXT NOT NULL,
            sha_detected TEXT NOT NULL,
            test_name TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT DEFAULT '',
            pr_link TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE odr_tests (
            id INTEGER PRIMARY KEY,
            project_url TEXT NOT NULL,
            sha_detected TEXT NOT NULL,
            module_path TEXT DEFAULT '',
            od_test TEXT NOT NULL,
            relevant_test_vp_bss TEXT DEFAULT '',
            relevant_test_vpc TEXT DEFAULT '',
            od_test_type TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE tic_fic_data (
            id INTEGER PRIMARY KEY,
            project_url TEXT NOT NULL,
            sha_detected TEXT NOT NULL,
            module_path TEXT NOT NULL,
            test_name TEXT NOT NULL,
            tic_eq_fic TEXT DEFAULT 'False',
            tic_sha TEXT DEFAULT '',
            fic_sha TEXT DEFAULT ''
        )
    """)

    pr_rows = [
        (1, "https://github.com/apache/hadoop", sha("pr1"), "hadoop-common",
         "org.apache.hadoop.fs.TestFileSystem.testCopyFromLocal",
         "OD", "Accepted", "https://github.com/apache/hadoop/pull/1234", ""),
        (2, "https://github.com/apache/hbase", sha("pr2"), "hbase-server",
         "org.apache.hadoop.hbase.TestHBaseCluster.testRegionSplit",
         "OD-Vic", "Opened", "", ""),
        (3, "https://github.com/google/guice", sha("pr3"), "core",
         "com.google.inject.internal.TestProvision.testSingleton",
         "ID", "DeveloperFixed", "https://github.com/google/guice/pull/567",
         "Fixed in commit"),
        (4, "https://github.com/square/retrofit", sha("pr4"), "retrofit",
         "retrofit2.TestCallAdapter.testEnqueueCallback",
         "NOD", "", "", ""),
        (5, "https://github.com/alibaba/fastjson", sha("pr5"), "fastjson",
         "com.alibaba.fastjson.TestSerializer.testDateFormat",
         "OD-Brit", "Accepted", "https://github.com/alibaba/fastjson/pull/890", ""),
        (6, "https://github.com/spring-projects/spring-framework", sha("pr6"),
         "spring-core",
         "org.springframework.core.io.TestResourceLoader.testClasspath",
         "NIO", "Opened", "", ""),
        (7, "https://github.com/elastic/elasticsearch", sha("pr7"), "server",
         "org.elasticsearch.search.TestAggregation.testTermsAgg",
         "OD", "MovedToGradle", "", "Moved to Gradle build"),
        (8, "https://github.com/ReactiveX/RxJava", sha("pr8"), "rxjava",
         "io.reactivex.rxjava3.TestFlowable.testBackpressure",
         "OD-Vic", "Accepted", "https://github.com/ReactiveX/RxJava/pull/321", ""),
        (9, "https://github.com/apache/flink", sha("pr9"), "flink-core",
         "org.apache.flink.api.TestDataStream.testMap",
         "TD", "", "", ""),
        (10, "https://github.com/apache/kafka", sha("pr10"), "clients",
         "org.apache.kafka.clients.TestProducer.testSendAsync",
         "OD", "Accepted", "https://github.com/apache/kafka/pull/456", ""),
        (11, "https://github.com/dropwizard/dropwizard", sha("pr11"),
         "dropwizard-core",
         "io.dropwizard.TestApplication.testGetResource",
         "NOD", "DeveloperFixed",
         "https://github.com/dropwizard/dropwizard/pull/789",
         "Fixed concurrency issue"),
        (12, "https://github.com/kiegroup/jbpm", sha("pr12"), "jbpm-flow",
         "org.jbpm.workflow.TestProcess.testSignalEvent",
         "ID", "Opened", "", ""),
        (13, "https://github.com/apache/hadoop", sha("pr13"), "hadoop-hdfs",
         "org.apache.hadoop.hdfs.TestDFSClient.testReadBlock",
         "NDOD", "", "", ""),
        (14, "https://github.com/google/guava", sha("pr14"), "guava",
         "com.google.common.collect.TestImmutableSet.testBuilder",
         "OD-Vic", "MovedToGradle", "", "Migrated to Gradle"),
        (15, "https://github.com/apache/hbase", sha("pr15"), "hbase-common",
         "org.apache.hadoop.hbase.util.TestBytes.testCompareTo",
         "OD", "Accepted", "https://github.com/apache/hbase/pull/999", ""),
        (16, "https://github.com/spring-projects/spring-framework", sha("pr16"),
         "spring-beans",
         "org.springframework.beans.TestBeanWrapper.testNestedProperty",
         "NOD", "", "", ""),
        (17, "https://github.com/alibaba/fastjson", sha("pr17"), "fastjson",
         "com.alibaba.fastjson.TestParser.testUnicode",
         "OD", "DeveloperFixed", "https://github.com/alibaba/fastjson/pull/111",
         "Unicode handling fix"),
        (18, "https://github.com/elastic/elasticsearch", sha("pr18"), "server",
         "org.elasticsearch.index.TestIndexService.testCreateIndex",
         "TZD", "Opened", "", ""),
        (19, "https://github.com/ReactiveX/RxJava", sha("pr19"), "rxjava",
         "io.reactivex.rxjava3.TestObservable.testSubscribeOn",
         "NIO", "", "", ""),
        (20, "https://github.com/apache/flink", sha("pr20"), "flink-runtime",
         "org.apache.flink.runtime.TestTaskManager.testHeartbeat",
         "OD", "Accepted", "https://github.com/apache/flink/pull/222", ""),
        (21, "https://github.com/apache/kafka", sha("pr21"), "streams",
         "org.apache.kafka.streams.TestKStreamJoin.testInnerJoin",
         "OD-Brit", "", "", ""),
        (22, "https://github.com/kiegroup/jbpm", sha("pr22"), "jbpm-runtime",
         "org.jbpm.runtime.TestManager.testCreateSession",
         "OD", "Opened", "", ""),
        (23, "https://github.com/google/guice", sha("pr23"), "extensions",
         "com.google.inject.persist.TestJpaModule.testTransaction",
         "ID", "DeveloperFixed", "https://github.com/google/guice/pull/333", ""),
        (24, "https://github.com/dropwizard/dropwizard", sha("pr24"),
         "dropwizard-jersey",
         "io.dropwizard.jersey.TestJerseyClient.testPost",
         "OD-Vic", "Accepted",
         "https://github.com/dropwizard/dropwizard/pull/444", ""),
        (25, "https://github.com/apache/hadoop", sha("pr25"), "hadoop-yarn",
         "org.apache.hadoop.yarn.TestNodeManager.testContainerLaunch",
         "OD", "", "", ""),
        (26, "https://github.com/apache/hbase", sha("pr26"), "hbase-server",
         "org.apache.hadoop.hbase.master.TestMasterProcedure.testAssignRegion",
         "OD-Vic", "Opened", "", ""),
        (27, "https://github.com/alibaba/fastjson", sha("pr27"), "fastjson",
         "com.alibaba.fastjson.TestJSONPath.testDeep",
         "NOD", "", "", ""),
        (28, "https://github.com/spring-projects/spring-framework", sha("pr28"),
         "spring-web",
         "org.springframework.web.TestDispatcherServlet.testHandleRequest",
         "OD", "Accepted",
         "https://github.com/spring-projects/spring-framework/pull/555", ""),
        (29, "https://github.com/elastic/elasticsearch", sha("pr29"), "x-pack",
         "org.elasticsearch.xpack.TestWatcher.testTrigger",
         "UD", "", "", ""),
        (30, "https://github.com/apache/flink", sha("pr30"), "flink-table",
         "org.apache.flink.table.TestSQLParser.testCreateTable",
         "OD-Brit", "", "", ""),
    ]

    c.executemany("INSERT INTO pr_data VALUES (?,?,?,?,?,?,?,?,?)", pr_rows)

    gr_rows = [
        (1, "https://github.com/gradle/gradle", sha("gr1"), "core",
         "org.gradle.api.TestProject.testApplyPlugin",
         "ID", "Opened", "", ""),
        (2, "https://github.com/linkedin/rest.li", sha("gr2"), "restli-server",
         "com.linkedin.restli.TestRestClient.testBatchGet",
         "OD", "Accepted", "https://github.com/linkedin/rest.li/pull/101", ""),
        (3, "https://github.com/ben-manes/caffeine", sha("gr3"), "caffeine",
         "com.github.benmanes.caffeine.cache.TestCache.testExpiry",
         "ID-HtF", "", "", ""),
        (4, "https://github.com/Netflix/zuul", sha("gr4"), "zuul-core",
         "com.netflix.zuul.TestFilters.testPreFilter",
         "OD-Vic", "Opened", "", ""),
        (5, "https://github.com/apache/beam", sha("gr5"), "sdks-java",
         "org.apache.beam.sdk.TestPipeline.testApply",
         "OD", "Accepted", "https://github.com/apache/beam/pull/201", ""),
        (6, "https://github.com/square/okhttp", sha("gr6"), "okhttp",
         "okhttp3.TestOkHttpClient.testConnectionPool",
         "NOD", "", "", ""),
        (7, "https://github.com/hibernate/hibernate-orm", sha("gr7"),
         "hibernate-core",
         "org.hibernate.test.TestSessionFactory.testOpenSession",
         "ID", "DeveloperFixed",
         "https://github.com/hibernate/hibernate-orm/pull/301", ""),
        (8, "https://github.com/apache/beam", sha("gr8"), "runners",
         "org.apache.beam.runners.TestDirectRunner.testExecute",
         "OD-Brit", "Opened", "", ""),
        (9, "https://github.com/apache/flink", sha("gr9"), "flink-runtime",
         "org.apache.flink.runtime.TestTaskManager.testHeartbeat",
         "OD", "Accepted", "https://github.com/apache/flink/pull/223", ""),
        (10, "https://github.com/Netflix/zuul", sha("gr10"), "zuul-filters",
         "com.netflix.zuul.filters.TestRoute.testForward",
         "NIO", "", "", ""),
        (11, "https://github.com/gradle/gradle", sha("gr11"), "build-logic",
         "org.gradle.build.TestDependencyCheck.testConflictResolution",
         "OD", "", "", ""),
        (12, "https://github.com/linkedin/rest.li", sha("gr12"), "restli-client",
         "com.linkedin.restli.TestClient.testRequest",
         "ID-HtF", "Accepted", "https://github.com/linkedin/rest.li/pull/102", ""),
    ]

    c.executemany("INSERT INTO gr_data VALUES (?,?,?,?,?,?,?,?,?)", gr_rows)

    py_rows = [
        (1, "https://github.com/pallets/flask", sha("py1"),
         "tests/test_app.py::TestFlask::test_config_from_env",
         "OD-Vic", "Opened", "", ""),
        (2, "https://github.com/psf/requests", sha("py2"),
         "tests/test_requests.py::TestSession::test_cookie_persistence",
         "NOD", "", "", ""),
        (3, "https://github.com/pandas-dev/pandas", sha("py3"),
         "pandas/tests/test_frame.py::TestDataFrame::test_sort_values",
         "OD-Brit", "Accepted", "https://github.com/pandas-dev/pandas/pull/401", ""),
        (4, "https://github.com/scikit-learn/scikit-learn", sha("py4"),
         "sklearn/tests/test_svm.py::TestSVC::test_predict",
         "NIO", "Opened", "", ""),
        (5, "https://github.com/django/django", sha("py5"),
         "tests/test_db.py::TestDatabase::test_migration",
         "OD", "", "", ""),
        (6, "https://github.com/pallets/click", sha("py6"),
         "tests/test_cli.py::TestGroup::test_command_chain",
         "OD-Vic", "Accepted", "https://github.com/pallets/click/pull/501", ""),
        (7, "https://github.com/pytest-dev/pytest", sha("py7"),
         "testing/test_runner.py::TestRunner::test_collect",
         "NOD", "", "", ""),
        (8, "https://github.com/celery/celery", sha("py8"),
         "t/unit/test_worker.py::TestWorker::test_start",
         "OD-Brit", "Opened", "", ""),
        (9, "https://github.com/django/django", sha("py9"),
         "tests/test_views.py::TestView::test_dispatch",
         "UD", "", "", ""),
        (10, "https://github.com/scikit-learn/scikit-learn", sha("py10"),
         "sklearn/tests/test_ensemble.py::TestRandomForest::test_fit",
         "OD-Vic", "", "", ""),
    ]

    c.executemany("INSERT INTO py_data VALUES (?,?,?,?,?,?,?,?)", py_rows)

    odr_rows = [
        (1, "https://github.com/apache/hadoop", sha("pr1"), "hadoop-common",
         "org.apache.hadoop.fs.TestFileSystem.testCopyFromLocal",
         "org.apache.hadoop.fs.TestPath.testResolve", "", "victim"),
        (2, "https://github.com/apache/hbase", sha("pr2"), "hbase-server",
         "org.apache.hadoop.hbase.TestHBaseCluster.testRegionSplit",
         "org.apache.hadoop.hbase.TestHBaseCluster.testCreateTable", "", "victim"),
        (3, "https://github.com/square/retrofit", sha("pr4"), "retrofit",
         "retrofit2.TestCallAdapter.testEnqueueCallback",
         "retrofit2.TestCallAdapter.testCancelCallback", "", "victim"),
        (4, "https://github.com/spring-projects/spring-framework", sha("pr16"),
         "spring-beans",
         "org.springframework.beans.TestBeanWrapper.testNestedProperty",
         "org.springframework.beans.TestPropertyEditor.testConvert", "", "victim"),
        (5, "https://github.com/ReactiveX/RxJava", sha("pr19"), "rxjava",
         "io.reactivex.rxjava3.TestObservable.testSubscribeOn",
         "io.reactivex.rxjava3.TestScheduler.testIo", "", "victim"),
        (6, "https://github.com/alibaba/fastjson", sha("pr5"), "fastjson",
         "com.alibaba.fastjson.TestSerializer.testDateFormat",
         "com.alibaba.fastjson.TestConfig.testInit", "", "brittle"),
        (7, "https://github.com/apache/kafka", sha("pr10"), "clients",
         "org.apache.kafka.clients.TestProducer.testSendAsync",
         "org.apache.kafka.clients.TestConsumer.testPoll", "", "victim"),
        (8, "https://github.com/ReactiveX/RxJava", sha("pr8"), "rxjava",
         "io.reactivex.rxjava3.TestFlowable.testBackpressure",
         "io.reactivex.rxjava3.TestScheduler.testCompute", "", "victim"),
        (9, "https://github.com/apache/hbase", sha("pr15"), "hbase-common",
         "org.apache.hadoop.hbase.util.TestBytes.testCompareTo",
         "org.apache.hadoop.hbase.util.TestBytes.testToString", "", "victim"),
        (10, "https://github.com/apache/hbase", sha("pr26"), "hbase-server",
         "org.apache.hadoop.hbase.master.TestMasterProcedure.testAssignRegion",
         "org.apache.hadoop.hbase.master.TestMasterProcedure.testUnassignRegion",
         "", "brittle"),
        (11, "https://github.com/spring-projects/spring-framework", sha("pr28"),
         "spring-web",
         "org.springframework.web.TestDispatcherServlet.testHandleRequest",
         "org.springframework.web.TestWebContext.testRefresh", "", "victim"),
        (12, "https://github.com/apache/flink", sha("pr20"), "flink-runtime",
         "org.apache.flink.runtime.TestTaskManager.testHeartbeat",
         "org.apache.flink.runtime.TestJobMaster.testRegister", "", "victim"),
        (13, "https://github.com/apache/flink", sha("pr30"), "flink-table",
         "org.apache.flink.table.TestSQLParser.testCreateTable",
         "org.apache.flink.table.TestCatalog.testRegister", "", "victim"),
        (14, "https://github.com/mockito/mockito", sha("odr14"), "core",
         "org.mockito.internal.TestMockCreation.testMockInterface",
         "org.mockito.internal.TestConfig.testInit", "", "victim"),
        (15, "https://github.com/assertj/assertj", sha("odr15"), "assertj-core",
         "org.assertj.core.api.TestAssertions.testIsEqualTo",
         "org.assertj.core.api.TestAbstractAssert.testDescribedAs", "", "brittle"),
    ]

    c.executemany("INSERT INTO odr_tests VALUES (?,?,?,?,?,?,?,?)", odr_rows)

    tic_fic_rows = [
        (1, "https://github.com/google/guice", sha("pr3"), "core",
         "com.google.inject.internal.TestProvision.testSingleton",
         "True", sha("tic1"), sha("fic1")),
        (2, "https://github.com/alibaba/fastjson", sha("pr17"), "fastjson",
         "com.alibaba.fastjson.TestParser.testUnicode",
         "False", sha("tic2"), sha("fic2")),
        (3, "https://github.com/apache/hadoop", sha("pr1"), "hadoop-common",
         "org.apache.hadoop.fs.TestFileSystem.testCopyFromLocal",
         "True", sha("tic3"), sha("fic3")),
        (4, "https://github.com/apache/kafka", sha("pr10"), "clients",
         "org.apache.kafka.clients.TestProducer.testSendAsync",
         "False", sha("tic4"), sha("fic4")),
        (5, "https://github.com/ReactiveX/RxJava", sha("pr8"), "rxjava",
         "io.reactivex.rxjava3.TestFlowable.testBackpressure",
         "True", sha("tic5"), sha("fic5")),
        (6, "https://github.com/spring-projects/spring-framework", sha("pr28"),
         "spring-web",
         "org.springframework.web.TestDispatcherServlet.testHandleRequest",
         "False", sha("tic6"), sha("fic6")),
        (7, "https://github.com/hibernate/hibernate-orm", sha("gr7"),
         "hibernate-core",
         "org.hibernate.test.TestSessionFactory.testOpenSession",
         "True", sha("tic7"), sha("fic7")),
        (8, "https://github.com/mockito/mockito", sha("tic_orphan"), "core",
         "org.mockito.internal.TestVerification.testTimesExact",
         "False", sha("tic8"), sha("fic8")),
        (9, "https://github.com/apache/hbase", sha("pr2"), "hbase-server",
         "org.apache.hadoop.hbase.TestHBaseCluster.testRegionSplit",
         "True", sha("tic9"), sha("fic9")),
        (10, "https://github.com/apache/flink", sha("pr9"), "flink-core",
         "org.apache.flink.api.TestDataStream.testMap",
         "False", sha("tic10"), sha("fic10")),
    ]

    c.executemany("INSERT INTO tic_fic_data VALUES (?,?,?,?,?,?,?,?)", tic_fic_rows)

    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    create_database()
