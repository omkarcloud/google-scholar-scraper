"""Tests that check the hosted service's exits (its gateway and its ladder of proxies).
This repo sends every request from your own connection, or through the one proxy
config.py names, so they are skipped here."""
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTED_EXIT_TESTS = {
    "google_scholar/test_fetch.py::test_a_refused_first_exit_is_held_for_that_surface_only",
    "google_scholar/test_fetch.py::test_a_served_call_clears_the_refusal_count",
    "google_scholar/test_fetch.py::test_every_refusal_form_moves_down_the_ladder",
    "google_scholar/test_fetch.py::test_every_try_refused_is_blocked",
    "google_scholar/test_fetch.py::test_exit_ladder_arithmetic",
    "google_scholar/test_fetch.py::test_refusals_in_a_row_wear_a_pass_out",
    "google_scholar/test_fetch.py::test_the_shipped_ladder",
}


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="checks the hosted service's exits; this repo sends requests direct")
    for item in items:
        path = os.path.relpath(str(item.fspath), HERE).replace(os.sep, "/")
        if path + "::" + item.nodeid.split("::", 1)[-1].split("[")[0] in HOSTED_EXIT_TESTS:
            item.add_marker(skip)
