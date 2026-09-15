"""JUnit XML report generation."""
from xml.etree.ElementTree import Element, SubElement, ElementTree


def generate_junit_xml(results, output_path):
    """Write JUnit XML from test results.

    Parameters
    ----------
    results : list[dict]
        Each dict has 'name' (str), 'passed' (bool), 'message' (str), 'time' (float).
    output_path : str
        Path for the output XML file.
    """
    testsuite = Element('testsuite')
    testsuite.set('name', 'stt_verifier')
    testsuite.set('tests', str(len(results)))

    failures = sum(1 for r in results if not r['passed'])
    testsuite.set('failures', str(failures))
    testsuite.set('errors', '0')

    total_time = sum(r.get('time', 0) for r in results)
    testsuite.set('time', f'{total_time:.3f}')

    for result in results:
        testcase = SubElement(testsuite, 'testcase')
        testcase.set('name', result['name'])
        testcase.set('classname', 'stt_verifier')
        testcase.set('time', f'{result.get("time", 0):.3f}')

        if not result['passed']:
            failure = SubElement(testcase, 'failure')
            failure.set('message', result.get('message', 'Test failed'))
            failure.text = result.get('message', '')

    tree = ElementTree(testsuite)
    tree.write(output_path, encoding='unicode', xml_declaration=True)
