# -*- coding: utf-8 -*-
"""Basic smoke tests for qqbot_agent_sdk."""

from qqbot_agent_sdk import EventParser, coerce_list, build_user_agent, QQBOT_VERSION


def test_version_string():
    assert isinstance(QQBOT_VERSION, str)
    assert QQBOT_VERSION


def test_user_agent_format():
    ua = build_user_agent()
    assert "QQBotAdapter" in ua
    assert "Python" in ua


def test_coerce_list_comma_string():
    assert coerce_list("a, b, c") == ["a", "b", "c"]


def test_coerce_list_empty():
    assert coerce_list(None) == []
    assert coerce_list("") == []


def test_event_parser_unknown_event():
    parser = EventParser()
    result = parser.parse("UNKNOWN_EVENT", {})
    assert result is None
