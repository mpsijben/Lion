"""Tests for lion.toon module - TOON encoder."""

from lion.toon import encode, _quote_if_needed


class TestEncode:
    """Tests for TOON encoding."""

    def test_simple_dict(self):
        result = encode({"name": "Alice", "age": 30})
        assert "name: Alice" in result
        assert "age: 30" in result

    def test_boolean_values(self):
        result = encode({"active": True, "deleted": False})
        assert "active: true" in result
        assert "deleted: false" in result

    def test_null_value(self):
        result = encode({"value": None})
        assert "value: null" in result

    def test_nested_dict(self):
        result = encode({"user": {"id": 1, "name": "Bob"}})
        assert "user:" in result
        assert "  id: 1" in result
        assert "  name: Bob" in result

    def test_primitive_list(self):
        result = encode({"tags": ["foo", "bar", "baz"]})
        assert "tags[3]: foo,bar,baz" in result

    def test_empty_list(self):
        result = encode({"items": []})
        assert "items[0]:" in result

    def test_tabular_array(self):
        data = {"agents": [
            {"id": 1, "model": "claude", "conf": 0.8},
            {"id": 2, "model": "gemini", "conf": 0.7},
        ]}
        result = encode(data)
        assert "agents[2]{id,model,conf}:" in result
        assert "1,claude,0.8" in result
        assert "2,gemini,0.7" in result

    def test_tabular_with_none(self):
        data = {"items": [
            {"name": "a", "lens": "arch"},
            {"name": "b", "lens": None},
        ]}
        result = encode(data)
        assert "null" in result

    def test_smaller_than_json(self):
        """TOON should be smaller than JSON for structured data."""
        import json
        data = {"issues": [
            {"severity": "critical", "title": "Bug", "file": "a.py"},
            {"severity": "warning", "title": "Style", "file": "b.py"},
            {"severity": "suggestion", "title": "Perf", "file": "c.py"},
        ]}
        json_size = len(json.dumps(data, indent=2))
        toon_size = len(encode(data))
        assert toon_size < json_size


class TestQuoting:
    """Tests for TOON quoting rules."""

    def test_no_quote_simple_string(self):
        assert _quote_if_needed("hello") == "hello"

    def test_quote_empty_string(self):
        assert _quote_if_needed("") == '""'

    def test_quote_string_with_colon(self):
        assert _quote_if_needed("key: value") == '"key: value"'

    def test_quote_string_with_comma(self):
        assert _quote_if_needed("a,b") == '"a,b"'

    def test_quote_boolean_string(self):
        assert _quote_if_needed("true") == '"true"'
        assert _quote_if_needed("false") == '"false"'

    def test_quote_numeric_string(self):
        assert _quote_if_needed("42") == '"42"'

    def test_no_quote_regular_text(self):
        assert _quote_if_needed("SQL injection in login") == "SQL injection in login"
