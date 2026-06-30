from __future__ import annotations

import pytest

from ai_config_sync.selectors import parse_selector, selection_matches


def test_parse_selector_forms():
    assert parse_selector("opencode").client == "opencode"
    selector = parse_selector("opencode:sense-nova:deepseek-v4-flash")
    assert selector.client == "opencode"
    assert selector.provider == "sense-nova"
    assert selector.model == "deepseek-v4-flash"


@pytest.mark.parametrize("value", ["", "opencode:", ":provider", "a:b:c:d"])
def test_parse_selector_invalid(value):
    with pytest.raises(ValueError, match="invalid selector|must not be empty"):
        parse_selector(value)


def test_selection_matches_granularity():
    selectors = [parse_selector("opencode:sense")]
    assert selection_matches(selectors, "opencode", "sense")
    assert selection_matches(selectors, "opencode", "sense", "model")
    assert not selection_matches(selectors, "opencode")
    assert not selection_matches(selectors, "claude-code", "sense")
