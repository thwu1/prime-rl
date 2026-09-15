"""JUnit XML test report generation."""
import xml.etree.ElementTree as ET


def generate_junit_xml(scenario_name, results):
    """Generate JUnit XML string from verification results.

    Each result dict has keys: utterance_id, expected_text, heard_text,
    hypothesis_text, wer, passed, threshold.
    """
    testsuite = ET.Element('testsuite')
    testsuite.set('name', scenario_name)
    testsuite.set('tests', str(len(results)))
    testsuite.set('failures', str(sum(1 for r in results if not r['passed'])))

    for r in results:
        tc = ET.SubElement(testsuite, 'testcase')
        tc.set('name', f"utterance_{r['utterance_id']}")
        if not r['passed']:
            failure = ET.SubElement(tc, 'failure')
            failure.set('message',
                        f"WER {r['wer']:.3f} exceeds threshold {r['threshold']:.1f}")
            failure.text = (
                f"Expected: {r['expected_text']}\n"
                f"Heard: {r['heard_text']}\n"
                f"Hypothesis: {r['hypothesis_text']}"
            )

    return ET.tostring(testsuite, encoding='unicode')
