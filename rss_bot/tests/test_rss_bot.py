import pytest

from rss_bot import load_feeds


def test_load_feeds():
    """ Load the content of an opml file"""
    # Setup
    opml_file = "../../feedlist.opml"

    # Exercise
    tree = load_feeds(opml_file)

    # Verify
    assert True