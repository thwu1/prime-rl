"""
Tests for the WAI-ARIA Virtual Screen Reader implementation.

"""

import pytest
import json
import sys
import os

sys.path.insert(0, '/app')
from screen_reader import VirtualScreenReader

FIXTURES_DIR = '/app/html_fixtures'
EXPECTED_FILE = '/app/expected_outputs.json'

with open(EXPECTED_FILE) as f:
    EXPECTED = json.load(f)


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return f.read()


def full_traversal(html):
    """Traverse the full document using next() until 'end of document'."""
    sr = VirtualScreenReader()
    sr.start(html)
    # Guard against infinite loop
    max_steps = 500
    steps = 0
    while sr.last_spoken_phrase() != 'end of document' and steps < max_steps:
        sr.next()
        steps += 1
    return sr.spoken_phrase_log()


class TestBasicTraversal:
    """Test basic page traversal with standard HTML landmarks and elements."""

    def test_basic_page(self):
        html = load_fixture('basic.html')
        result = full_traversal(html)
        assert result == EXPECTED['basic']['traversal']

    def test_correct_heading_levels(self):
        html = load_fixture('basic.html')
        result = full_traversal(html)
        assert 'heading, Page Title, level 1' in result
        assert 'heading, Article Heading, level 2' in result

    def test_footer_maps_to_contentinfo(self):
        html = load_fixture('basic.html')
        result = full_traversal(html)
        assert 'contentinfo' in result
        assert 'end of contentinfo' in result


class TestHiddenElements:
    """Test that aria-hidden and hidden elements are excluded from the tree."""

    def test_hidden_elements_excluded(self):
        html = load_fixture('hidden.html')
        result = full_traversal(html)
        assert result == EXPECTED['hidden']['traversal']

    def test_no_hidden_text_in_output(self):
        html = load_fixture('hidden.html')
        result = full_traversal(html)
        for phrase in result:
            assert 'Hidden' not in phrase
            assert 'hidden' not in phrase.lower() or phrase == 'end of document'


class TestHeadingsAndLinks:
    """Test heading/link nesting with childrenPresentational behavior."""

    def test_headings_links_traversal(self):
        html = load_fixture('headings_links.html')
        result = full_traversal(html)
        assert result == EXPECTED['headings_links']['traversal']

    def test_heading_containing_link_is_container(self):
        """A heading with a focusable link child should be a container (has end marker)."""
        html = load_fixture('headings_links.html')
        result = full_traversal(html)
        assert 'end of heading, Heading With Link, level 1' in result

    def test_link_containing_heading_is_container(self):
        """A link containing a heading should be a container."""
        html = load_fixture('headings_links.html')
        result = full_traversal(html)
        assert 'end of link, Link With Heading' in result

    def test_link_inside_heading_is_leaf(self):
        """Link inside heading should be a leaf (text consumed by childrenPresentational pass-through)."""
        html = load_fixture('headings_links.html')
        result = full_traversal(html)
        link_idx = result.index('link, Heading With Link')
        # Next element should be end of heading, not text content
        assert result[link_idx + 1] == 'end of heading, Heading With Link, level 1'


class TestInertWithModal:
    """Test inert attribute handling with modal dialog escape."""

    def test_inert_modal_traversal(self):
        html = load_fixture('inert_modal.html')
        result = full_traversal(html)
        assert result == EXPECTED['inert_modal']['traversal']

    def test_inert_elements_hidden(self):
        html = load_fixture('inert_modal.html')
        result = full_traversal(html)
        assert 'hidden paragraph' not in ' '.join(result)

    def test_modal_dialog_escapes_inert(self):
        html = load_fixture('inert_modal.html')
        result = full_traversal(html)
        assert 'dialog, visible dialog heading, modal' in result

    def test_dialog_children_visible(self):
        html = load_fixture('inert_modal.html')
        result = full_traversal(html)
        assert 'heading, visible dialog heading, level 1' in result


class TestAriaOwns:
    """Test aria-owns reparenting of elements."""

    def test_aria_owns_traversal(self):
        html = load_fixture('aria_owns.html')
        result = full_traversal(html)
        assert result == EXPECTED['aria_owns']['traversal']

    def test_owned_item_inside_list(self):
        """Owned item should appear inside the list, not after it."""
        html = load_fixture('aria_owns.html')
        result = full_traversal(html)
        owned_idx = result.index('Owned Item 3')
        end_list_idx = result.index('end of list')
        assert owned_idx < end_list_idx

    def test_owned_item_after_regular_items(self):
        """Owned item should appear after regular items."""
        html = load_fixture('aria_owns.html')
        result = full_traversal(html)
        item2_idx = result.index('Item 2')
        owned_idx = result.index('Owned Item 3')
        assert owned_idx > item2_idx


class TestAriaLabels:
    """Test aria-label and aria-labelledby accessible name computation."""

    def test_aria_labels_traversal(self):
        html = load_fixture('aria_labels.html')
        result = full_traversal(html)
        assert result == EXPECTED['aria_labels']['traversal']

    def test_aria_label_on_nav(self):
        html = load_fixture('aria_labels.html')
        result = full_traversal(html)
        assert 'navigation, Primary' in result
        assert 'navigation, Secondary' in result

    def test_section_with_labelledby_gets_region_role(self):
        html = load_fixture('aria_labels.html')
        result = full_traversal(html)
        assert 'region, Featured Content' in result
        assert 'end of region, Featured Content' in result


class TestPresentationalRoles:
    """Test role='presentation' and role='none' behavior."""

    def test_presentational_traversal(self):
        html = load_fixture('presentational.html')
        result = full_traversal(html)
        assert result == EXPECTED['presentational']['traversal']

    def test_presentation_children_promoted(self):
        """Children of presentational elements should be promoted to parent."""
        html = load_fixture('presentational.html')
        result = full_traversal(html)
        # Paragraph from inside role=presentation div should appear at main level
        assert 'Presentation child' in ' '.join(result)

    def test_none_children_promoted(self):
        """Children of role=none elements should be promoted."""
        html = load_fixture('presentational.html')
        result = full_traversal(html)
        assert 'None child' in ' '.join(result)

    def test_button_is_leaf(self):
        """Button with childrenPresentational should be a leaf."""
        html = load_fixture('presentational.html')
        result = full_traversal(html)
        assert 'button, Click Me' in result
        btn_idx = result.index('button, Click Me')
        # Next should be end of main, not text content
        assert result[btn_idx + 1] == 'end of main'


class TestRoledescription:
    """Test aria-roledescription custom role names."""

    def test_roledescription_traversal(self):
        html = load_fixture('roledescription.html')
        result = full_traversal(html)
        assert result == EXPECTED['roledescription']['traversal']

    def test_custom_role_in_spoken_phrase(self):
        html = load_fixture('roledescription.html')
        result = full_traversal(html)
        assert 'slide, Slide 1' in result
        assert 'end of slide, Slide 1' in result


class TestHeadingNavigation:
    """Test heading navigation commands."""

    def test_move_to_next_heading(self):
        html = load_fixture('heading_nav.html')
        sr = VirtualScreenReader()
        sr.start(html)

        sr.perform('moveToNextHeading')
        assert sr.last_spoken_phrase() == 'heading, First Heading, level 1'

        sr.perform('moveToNextHeading')
        assert sr.last_spoken_phrase() == 'heading, Second Heading, level 2'

        sr.perform('moveToNextHeading')
        assert sr.last_spoken_phrase() == 'heading, Third Heading, level 3'

    def test_move_to_previous_heading(self):
        html = load_fixture('heading_nav.html')
        sr = VirtualScreenReader()
        sr.start(html)

        # Move to last heading
        sr.perform('moveToNextHeading')
        sr.perform('moveToNextHeading')
        sr.perform('moveToNextHeading')
        assert sr.last_spoken_phrase() == 'heading, Third Heading, level 3'

        sr.perform('moveToPreviousHeading')
        assert sr.last_spoken_phrase() == 'heading, Second Heading, level 2'

        sr.perform('moveToPreviousHeading')
        assert sr.last_spoken_phrase() == 'heading, First Heading, level 1'

    def test_move_to_next_heading_level(self):
        html = load_fixture('heading_nav.html')
        sr = VirtualScreenReader()
        sr.start(html)

        sr.perform('moveToNextHeadingLevel2')
        assert sr.last_spoken_phrase() == 'heading, Second Heading, level 2'

    def test_move_to_next_heading_level_no_match(self):
        html = load_fixture('heading_nav.html')
        sr = VirtualScreenReader()
        sr.start(html)

        result = sr.perform('moveToNextHeadingLevel4')
        assert result is None
        # Cursor should not have moved
        assert sr.last_spoken_phrase() == 'document'

    def test_heading_navigation_wraps(self):
        html = load_fixture('heading_nav.html')
        sr = VirtualScreenReader()
        sr.start(html)

        sr.perform('moveToNextHeading')
        sr.perform('moveToNextHeading')
        sr.perform('moveToNextHeading')
        assert sr.last_spoken_phrase() == 'heading, Third Heading, level 3'

        # Wraps around to first heading
        sr.perform('moveToNextHeading')
        assert sr.last_spoken_phrase() == 'heading, First Heading, level 1'


class TestLandmarkNavigation:
    """Test landmark navigation commands."""

    def test_move_to_next_landmark(self):
        html = load_fixture('landmark_nav.html')
        sr = VirtualScreenReader()
        sr.start(html)

        sr.perform('moveToNextLandmark')
        assert sr.last_spoken_phrase() == 'navigation, Main Nav'

        sr.perform('moveToNextLandmark')
        assert sr.last_spoken_phrase() == 'main'

        sr.perform('moveToNextLandmark')
        assert sr.last_spoken_phrase() == 'complementary'

        sr.perform('moveToNextLandmark')
        assert sr.last_spoken_phrase() == 'contentinfo'

    def test_move_to_previous_landmark(self):
        html = load_fixture('landmark_nav.html')
        sr = VirtualScreenReader()
        sr.start(html)

        # Move to contentinfo
        sr.perform('moveToNextLandmark')
        sr.perform('moveToNextLandmark')
        sr.perform('moveToNextLandmark')
        sr.perform('moveToNextLandmark')
        assert sr.last_spoken_phrase() == 'contentinfo'

        sr.perform('moveToPreviousLandmark')
        assert sr.last_spoken_phrase() == 'complementary'


class TestPreviousNavigation:
    """Test previous() navigation and wrap-around behavior."""

    def test_previous_basic(self):
        html = load_fixture('basic.html')
        sr = VirtualScreenReader()
        sr.start(html)

        sr.next()  # navigation
        sr.next()  # Nav Text
        assert sr.last_spoken_phrase() == 'Nav Text'

        sr.previous()
        assert sr.last_spoken_phrase() == 'navigation'

    def test_next_wraps_to_start(self):
        html = load_fixture('basic.html')
        sr = VirtualScreenReader()
        sr.start(html)

        while sr.last_spoken_phrase() != 'end of document':
            sr.next()

        sr.next()
        assert sr.last_spoken_phrase() == 'document'

    def test_previous_wraps_to_end(self):
        html = load_fixture('basic.html')
        sr = VirtualScreenReader()
        sr.start(html)
        # At index 0 (document), previous should wrap to last element
        sr.previous()
        assert sr.last_spoken_phrase() == 'end of document'


class TestClearLog:
    """Test spoken phrase log management."""

    def test_clear_spoken_phrase_log(self):
        html = load_fixture('basic.html')
        sr = VirtualScreenReader()
        sr.start(html)
        sr.next()
        sr.next()
        assert len(sr.spoken_phrase_log()) == 3

        sr.clear_spoken_phrase_log()
        assert sr.spoken_phrase_log() == []

    def test_spoken_phrase_log_is_copy(self):
        html = load_fixture('basic.html')
        sr = VirtualScreenReader()
        sr.start(html)
        log = sr.spoken_phrase_log()
        sr.next()
        # Original log should not be mutated
        assert len(log) == 1
        assert len(sr.spoken_phrase_log()) == 2
