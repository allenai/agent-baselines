import logging
import re
import time

from agent_baselines.solvers.code_agent.llm_agent import (
    clean_observation,
    delete_lines_containing,
)

logger = logging.getLogger(__name__)


def test_delete_lines_containing():
    text = "This is a test.\nThis line should be deleted because it contains 'gcc'.\nAnother line.\n"

    # Simple case with a literal string
    assert delete_lines_containing("gcc", text) == re.sub(r".*gcc.*\n", "", text)

    # Case with a regex pattern
    pat = r"Dropout\(p="
    text = "This is a test.\nThis line should be deleted because it contains 'Dropout(p=0.1)'. \nAnother line.\n"
    assert delete_lines_containing(pat, text) == re.sub(r".*" + pat + r".*\n", "", text)

    # Check that it handles empty strings correctly
    assert delete_lines_containing("gcc", "") == ""
    assert delete_lines_containing(r"Dropout\(p=", "") == ""


def test_clean_observation():
    # We trust that the patterns are correct if `delete_lines_containing`
    # works, so the main thing to check here is that it doesn't have
    # pathological behavior for very long strings.  From initial testing, about
    # 2**15 chars in a single line takes several seconds with the old broken
    # version, when it should be very fast (easily 0.01 seconds or less)

    # Simple case to confirm basic functionality
    text = "This is a test.\nThis line should be deleted because it contains 'gcc'.\nAnother line.\n"
    assert clean_observation(text) == "This is a test.\nAnother line.\n"

    # Test for long text
    longlen = 2**13
    long_text = (
        ("A" * longlen)
        + "\nThis line should be deleted because it contains 'gcc'.\n"
        + ("B" * longlen)
        + "\n"
    )
    start_time = time.perf_counter()
    cleaned_text = clean_observation(long_text)
    end_time = time.perf_counter()

    assert (
        end_time - start_time
    ) < 0.01, "clean_observation took too long for long text; there may be a pathological regex"
    assert (
        cleaned_text == ("A" * longlen) + "\n" + ("B" * longlen) + "\n"
    ), "clean_observation did not clean long text correctly"
