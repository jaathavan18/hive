"""JSON Tool - Validate, transform, merge, diff, and format JSON data."""

from __future__ import annotations

import json
import re

from fastmcp import FastMCP

MAX_INPUT_SIZE = 1_000_000  # 1 MB
MAX_DEPTH = 50


class _DepthCheckDecoder(json.JSONDecoder):
    """JSON decoder that enforces a maximum nesting depth during parsing."""

    def __init__(self, max_depth: int = MAX_DEPTH, **kwargs):
        self._max_depth = max_depth
        super().__init__(**kwargs)

    def decode(self, s: str, _w=json.decoder.WHITESPACE.match) -> object:
        self._check_nesting(s)
        return super().decode(s, _w)

    def _check_nesting(self, s: str) -> None:
        depth = 0
        in_string = False
        escape = False
        for ch in s:
            if escape:
                escape = False
                continue
            if ch == '\\' and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in ('{', '['):
                depth += 1
                if depth > self._max_depth:
                    raise ValueError(f"Exceeds maximum nesting depth of {self._max_depth}")
            elif ch in ('}', ']'):
                depth -= 1


_decoder = _DepthCheckDecoder(MAX_DEPTH)


def _parse_json(raw: str, name: str = "data") -> tuple[object, dict | None]:
    """Parse a JSON string with size and depth limits."""
    if not raw or not raw.strip():
        return None, {"error": f"{name} cannot be empty"}
    if len(raw) > MAX_INPUT_SIZE:
        return None, {"error": f"{name} exceeds maximum size of {MAX_INPUT_SIZE} characters"}
    try:
        parsed = _decoder.decode(raw)
    except json.JSONDecodeError as e:
        return None, {"error": f"Invalid JSON in {name}: {e}"}
    except ValueError as e:
        return None, {"error": f"{name}: {e}"}
    return parsed, None


_BRACKET_SPLIT = re.compile(r"(\[[^\]]*\])")
_BRACKET_INDEX = re.compile(r"\[(\d+)\]")
_WILDCARD = re.compile(r"\[\*\]")


def _resolve_path(obj: object, expression: str) -> object:
    """Resolve a dot-notation path against a JSON object. Supports [*] wildcard."""
    tokens: list[str] = []
    for part in expression.split("."):
        for seg in _BRACKET_SPLIT.split(part):
            if seg:
                tokens.append(seg)

    return _walk(obj, tokens, 0)


def _walk(current: object, tokens: list[str], idx: int) -> object:
    """Recursively walk the token path, expanding wildcards."""
    if idx >= len(tokens):
        return current

    token = tokens[idx]

    # Wildcard: expand over all elements
    if _WILDCARD.fullmatch(token):
        if not isinstance(current, list):
            raise TypeError(f"Expected list for [*], got {type(current).__name__}")
        return [_walk(item, tokens, idx + 1) for item in current]

    # Numeric index
    bracket = _BRACKET_INDEX.fullmatch(token)
    if bracket:
        i = int(bracket.group(1))
        if not isinstance(current, list):
            raise TypeError(f"Expected list for index [{i}], got {type(current).__name__}")
        if i >= len(current):
            raise IndexError(f"Index [{i}] out of range (length {len(current)})")
        return _walk(current[i], tokens, idx + 1)

    # Dict key
    if not isinstance(current, dict):
        raise TypeError(f"Expected object for key '{token}', got {type(current).__name__}")
    if token not in current:
        raise KeyError(f"Key '{token}' not found. Available keys: {list(current.keys())}")
    return _walk(current[token], tokens, idx + 1)


def _deep_merge(base: object, override: object) -> object:
    """Recursively merge override into base. Override wins on conflicts."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    # For non-dict types or type mismatches, override wins
    return override


def _diff(first: object, second: object, path: str = "") -> list[dict]:
    """Compute structural differences between two JSON-compatible objects."""
    diffs: list[dict] = []
    prefix = path or "$"

    if type(first) != type(second):
        diffs.append({
            "path": prefix,
            "type": "type_changed",
            "from": type(first).__name__,
            "to": type(second).__name__,
            "old_value": first,
            "new_value": second,
        })
        return diffs

    if isinstance(first, dict) and isinstance(second, dict):
        all_keys = set(first.keys()) | set(second.keys())
        for key in sorted(all_keys):
            child_path = f"{prefix}.{key}"
            if key not in first:
                diffs.append({"path": child_path, "type": "added", "value": second[key]})
            elif key not in second:
                diffs.append({"path": child_path, "type": "removed", "value": first[key]})
            else:
                diffs.extend(_diff(first[key], second[key], child_path))
    elif isinstance(first, list) and isinstance(second, list):
        max_len = max(len(first), len(second))
        for i in range(max_len):
            child_path = f"{prefix}[{i}]"
            if i >= len(first):
                diffs.append({"path": child_path, "type": "added", "value": second[i]})
            elif i >= len(second):
                diffs.append({"path": child_path, "type": "removed", "value": first[i]})
            else:
                diffs.extend(_diff(first[i], second[i], child_path))
    elif first != second:
        diffs.append({
            "path": prefix,
            "type": "changed",
            "old_value": first,
            "new_value": second,
        })

    return diffs


def register_tools(mcp: FastMCP) -> None:
    """Register JSON tools with the MCP server."""

    @mcp.tool()
    def json_validate(
        data: str,
        schema: str,
    ) -> dict:
        """
        Validate JSON data against a JSON Schema.

        Args:
            data: JSON string to validate
            schema: JSON Schema string to validate against

        Returns:
            dict with validation result, errors if any
        """
        try:
            parsed, err = _parse_json(data, "data")
            if err:
                return err

            schema_obj, err = _parse_json(schema, "schema")
            if err:
                return err

            if not isinstance(schema_obj, dict):
                return {"error": "schema must be a JSON object"}

            try:
                import jsonschema
            except ImportError:
                return {
                    "error": (
                        "jsonschema not installed. "
                        "Install with: pip install jsonschema"
                    )
                }

            errors = []
            validator = jsonschema.Draft7Validator(schema_obj)
            for error in validator.iter_errors(parsed):
                errors.append({
                    "message": error.message,
                    "path": list(error.absolute_path),
                })

            return {
                "valid": len(errors) == 0,
                "errors": errors,
                "error_count": len(errors),
            }

        except Exception as e:
            return {"error": f"Validation failed: {str(e)}"}

    @mcp.tool()
    def json_transform(
        data: str,
        expression: str,
    ) -> dict:
        """
        Extract or reshape data from a JSON structure using dot-notation paths.

        Supports nested keys, array indices, and chained access.

        Args:
            data: JSON string to extract from
            expression: Dot-notation path (e.g., "users[0].name", "config.database.host")

        Returns:
            dict with the extracted value

        Examples:
            expression="name"              -> top-level key
            expression="users[0]"          -> first array element
            expression="users[0].email"    -> nested field in array element
            expression="config.db.host"    -> deeply nested key
            expression="users[*].name"     -> all "name" values from array
        """
        try:
            parsed, err = _parse_json(data, "data")
            if err:
                return err

            if not expression or not expression.strip():
                return {"error": "expression cannot be empty"}

            result = _resolve_path(parsed, expression.strip())

            return {
                "success": True,
                "expression": expression,
                "result": result,
                "result_type": type(result).__name__,
            }

        except (KeyError, IndexError, TypeError) as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Transform failed: {str(e)}"}

    @mcp.tool()
    def json_merge(
        base: str,
        override: str,
    ) -> dict:
        """
        Deep merge two JSON objects. Values in override take precedence on conflicts.

        Nested objects are merged recursively. Arrays and primitives in override
        replace the corresponding values in base.

        Args:
            base: JSON string for the base object
            override: JSON string for the override object

        Returns:
            dict with the merged result
        """
        try:
            base_obj, err = _parse_json(base, "base")
            if err:
                return err

            override_obj, err = _parse_json(override, "override")
            if err:
                return err

            if not isinstance(base_obj, dict):
                return {"error": "base must be a JSON object"}
            if not isinstance(override_obj, dict):
                return {"error": "override must be a JSON object"}

            merged = _deep_merge(base_obj, override_obj)

            return {
                "success": True,
                "result": merged,
            }

        except Exception as e:
            return {"error": f"Merge failed: {str(e)}"}

    @mcp.tool()
    def json_diff(
        first: str,
        second: str,
    ) -> dict:
        """
        Compare two JSON structures and return their differences.

        Detects added keys, removed keys, changed values, and type changes.
        Paths use dot-notation with array indices (e.g., "$.users[0].name").

        Args:
            first: First JSON string
            second: Second JSON string

        Returns:
            dict with list of differences and whether the objects are equal
        """
        try:
            first_obj, err = _parse_json(first, "first")
            if err:
                return err

            second_obj, err = _parse_json(second, "second")
            if err:
                return err

            diffs = _diff(first_obj, second_obj)

            return {
                "equal": len(diffs) == 0,
                "differences": diffs,
                "difference_count": len(diffs),
            }

        except Exception as e:
            return {"error": f"Diff failed: {str(e)}"}

    @mcp.tool()
    def json_format(
        data: str,
        indent: int = 2,
        sort_keys: bool = False,
    ) -> dict:
        """
        Pretty print or minify JSON data.

        Args:
            data: JSON string to format
            indent: Number of spaces for indentation (0 = minify, 1-8 for pretty print)
            sort_keys: If True, sort object keys alphabetically for deterministic output

        Returns:
            dict with the formatted JSON string
        """
        try:
            parsed, err = _parse_json(data, "data")
            if err:
                return err

            if indent < 0 or indent > 8:
                return {"error": "indent must be 0-8"}

            if indent == 0:
                formatted = json.dumps(
                    parsed, separators=(",", ":"), ensure_ascii=False, sort_keys=sort_keys,
                )
            else:
                formatted = json.dumps(
                    parsed, indent=indent, ensure_ascii=False, sort_keys=sort_keys,
                )

            return {
                "success": True,
                "result": formatted,
                "minified": indent == 0,
            }

        except Exception as e:
            return {"error": f"Format failed: {str(e)}"}
