# JSON Tool

Validate, transform, merge, diff, and format JSON data. Pure Python — no external binaries required.

## Tools

### `json_validate`

Validate JSON data against a JSON Schema (Draft 7).

```
data: '{"name": "Alice", "age": 30}'
schema: '{"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}'
```

Requires `jsonschema` package: `pip install jsonschema`

### `json_transform`

Extract values using dot-notation paths.

```
data: '{"users": [{"name": "Alice"}, {"name": "Bob"}]}'
expression: "users[0].name"
→ "Alice"
```

Supported syntax:
- `key` — top-level key
- `key.subkey` — nested key
- `items[0]` — array index
- `items[0].name` — chained access

### `json_merge`

Deep merge two JSON objects. Override values take precedence.

```
base: '{"a": 1, "nested": {"x": 1, "y": 2}}'
override: '{"b": 2, "nested": {"y": 99}}'
→ {"a": 1, "b": 2, "nested": {"x": 1, "y": 99}}
```

### `json_diff`

Compare two JSON structures and list differences.

```
first: '{"a": 1, "b": 2}'
second: '{"a": 1, "b": 3, "c": 4}'
→ [{"path": "$.b", "type": "changed"}, {"path": "$.c", "type": "added"}]
```

### `json_format`

Pretty print or minify JSON.

```
data: '{"a":1,"b":2}'
indent: 2    → pretty printed
indent: 0    → minified
```

## Safety Limits

- Max input size: 1 MB
- Max nesting depth: 50 levels

## Dependencies

- `jsonschema` (optional, only needed for `json_validate`)
