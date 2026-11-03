# scenario_config -- Authoritative Schema

This is the platform contract for `bot_config.scenario_config`. Match it exactly. Load this before writing JSON.

## Top level: ScenarioConfig

| Field                | Type                          | Required       | Notes                                                                                                                                                                                 |
| -------------------- | ----------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`               | string                        | **yes (FE)**   | Identifier for the config. Required by FE JSON schema; not in backend_v1 Pydantic model.                                                                                             |
| `start`              | string                        | **yes**        | Key of the entry scenario. Must exist in `scenarios`. Must be a valid identifier (`^[a-z][a-z0-9_]{2,63}$`).                                                                          |
| `global_prompt`      | object                        | **yes**        | Required by both FE and backend_v1. Keys must be snake_case. Required sub-fields: `persona`, `context`, `conversation_style`, `guardrails`.                                           |
| `variables_schema`   | dict[str, VariableDefinition] | **yes (FE)**   | FE JSON schema requires it; backend_v1 defaults to `{}`. Include it always.                                                                                                           |
| `global_transitions` | dict[str, GlobalTransition]   | **yes (FE)**   | FE JSON schema requires it; backend_v1 defaults to `{}`. Include it always (use `{}` if none).                                                                                        |
| `scenarios`          | dict[str, Scenario]           | **yes**        | The scenarios. At least one required. Keys must be valid identifiers.                                                                                                                 |

### global_prompt key and value rules

- Keys render as headings in the UI.
- Must match: `^[a-z][a-z0-9_]{2,63}$` (lowercase + underscores, 3-64 chars).
- **WRONG**: `conversationStyle`, `languageRules`, `FAQ` (camelCase, uppercase, or too short).
- **RIGHT**: `conversation_style`, `language_rules`, `faq_reference`.

**Required fields** (must be non-empty after trim):
- `persona` -- who the agent is, brand, warmth, tone.
- `context` -- call type, who the customer is, product details.
- `conversation_style` -- language rules, length, acknowledgement style. Backend_v1 also accepts alias `conversationStyle`.
- `guardrails` -- compliance rules, scope limits.

**Optional extra keys** (e.g. `language_rules`, `faq_reference`) are allowed but must follow identifier regex.

**Max value length**: 3000 characters per field (newlines `\n`/`\r` excluded from count).

## VariableDefinition

| Field         | Type                                            | Required           | Notes                          |
| ------------- | ----------------------------------------------- | ------------------ | ------------------------------ |
| `source`      | enum: `system` \| `user_defined` \| `extracted` | **yes**            | How the variable is populated. |
| `description` | string                                          | no but recommended | Max 256 characters.            |

- **system**: auto-populated by the platform at call start. Must still be declared in schema.
- **user_defined**: known before the call -- CRM/contact fields and fixed values.
- **extracted**: produced during the call by a scenario's `extract`.

**Max 100 variables** total across all sources.

### Known system variables

Always available: `agent_name`, `agent_gender`, `agent_personality`, `current_time`, `current_date`, `current_day`, `current_timestamp`, `dialled_phone_number`, `conversation_id`.

Campaign manager variables (when active): `outbound_attempt_number`, `outbound_connected_attempt_number`, `call_direction`, `channel`, `last_disposition`.

## GlobalTransition

| Field                    | Type                     | Required | Notes                                                                       |
| ------------------------ | ------------------------ | -------- | --------------------------------------------------------------------------- |
| `when_llm`               | string                   | **yes**  | Natural-language trigger. Min 1 non-whitespace char.                        |
| `go_to`                  | string                   | **yes**  | Handler scenario key. **Must be unique across all global transitions.**     |
| `deterministic_exit_cue` | dict[str,string] \| null | no       | Language-keyed cue. Must cover all bot languages when present.              |

**Constraints:**

- Global transitions are LLM-triggered only (no `when` rule-based conditions).
- **No `signal` field** -- the `signal` field does not exist in the FE or backend_v1 authoring schema. The backend_v1 `GlobalTransition` model uses `extra="forbid"`, so including `signal` causes a Pydantic error.
- **Each `go_to` must be unique** within global_transitions -- no two global transitions can point to the same scenario. Create separate handler scenarios if needed.

## Scenario

| Field         | Type                      | Required        | Notes                                                                                               |
| ------------- | ------------------------- | --------------- | --------------------------------------------------------------------------------------------------- |
| `type`        | string                    | **yes (FE)**    | Always `"single_prompt"`. Required by the frontend. Backend_v1 defaults it but FE needs it explicit. |
| `prompt`      | string                    | **yes**         | Min 1 char (backend_v1). Behaviour + say blocks + Jinja + `<tool_name>` tags at end.                |
| `tools`       | array[string]             | no              | Tool names available in this scenario. Must match `<tool_name>` tags in `prompt` in name and order. |
| `extract`     | dict[str,string]          | no              | `variable_name -> extraction instruction`. Runs every turn.                                         |
| `transitions` | array[ScenarioTransition] | no              | Ordered; first match wins. Empty `[]` = terminal scenario.                                          |

### Tool attachment in scenarios

Tools are scoped per scenario. To attach tools:

1. Declare tool names in the scenario's `"tools"` array: `["search_place", "save_kundli"]`.
2. Append `<tool_name>` tags to the **end** of the scenario's `prompt`: `<tool_name>search_place</tool_name> <tool_name>save_kundli</tool_name>`.
3. The names and order of `<tool_name>` tags in `prompt` must match the `"tools"` array exactly.
4. Scenarios without tools set `"tools": []` and omit `<tool_name>` tags from `prompt`.

When the full `bot_config` is available, cross-check that tool names exist in the bot's `actions` list.

## ScenarioTransition

| Field                    | Type                        | Required | Notes                                                                     |
| ------------------------ | --------------------------- | -------- | ------------------------------------------------------------------------- |
| `go_to`                  | string                      | **yes**  | Destination scenario key. Min 1 char.                                     |
| `when`                   | TransitionCondition \| null | no       | Rule-based condition. Use exactly one of `when` or `when_llm`.            |
| `when_llm`               | string \| null              | no       | AI-judged intent trigger. Use exactly one of `when` or `when_llm`.        |
| `deterministic_exit_cue` | dict[str,string] \| null    | no       | Language-keyed cue. Should cover all bot languages.                       |

**`signal` is NOT part of the authoring schema.** The FE has no signal field. The backend_v1 `ScenarioTransition` uses `extra="forbid"`, so including `signal` causes a Pydantic error. The `signal` field exists only in the runtime engine (`genvoice_backend`) and should not appear in authored configs unless explicitly targeting the runtime directly.

Use **exactly one** of `when` or `when_llm` per transition. Order transitions so the most specific/deterministic fire first.

## TransitionCondition (the `when` grammar)

### Leaf -- TransitionConditionLeaf

| Field   | Type   | Required    | Notes                                                                                                                     |
| ------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------------------------- |
| `var`   | string | **yes**     | Variable name (must exist in `variables_schema`). Min 1 char.                                                             |
| `op`    | enum   | **yes**     | One of: `EQUALS`, `NOT_EQUALS`, `EXISTS`, `NOT_EXISTS` (UPPERCASE only).                                                  |
| `value` | string | conditional | **Required** for `EQUALS`/`NOT_EQUALS` (always a string, non-null). **Must be `null` or omitted** for `EXISTS`/`NOT_EXISTS`. |

### Operator rules (critical -- most common validation errors)

| Operator     | `value` field                     | Example                                                   |
| ------------ | --------------------------------- | --------------------------------------------------------- |
| `EQUALS`     | Required, always a non-null string | `{"var": "is_employed", "op": "EQUALS", "value": "true"}` |
| `NOT_EQUALS` | Required, always a non-null string | `{"var": "status", "op": "NOT_EQUALS", "value": "done"}`  |
| `EXISTS`     | **Must be `null` or omitted**      | `{"var": "callback_time", "op": "EXISTS"}`                |
| `NOT_EXISTS` | **Must be `null` or omitted**      | `{"var": "callback_time", "op": "NOT_EXISTS"}`            |

- The FE serializes EXISTS/NOT_EXISTS with `"value": null`. The backend_v1 accepts either `null` or absent. Both are valid.
- **Never use**: `==`, `!=`, `exists`, `not exists` (wrong casing), `EQUALS` without value, `EXISTS` with a non-null value, `"value": true` (boolean -- values are always strings).

### Condition limits (backend_v1)

- Max `and`/`or` nesting depth: **2 levels**.
- Max leaves per `and`/`or` array: **10**.
- Empty `and: []` or `or: []` arrays are rejected.

### Group -- TransitionConditionGroup (recursive)

```json
{ "and": [ <leaf|group>, ... ] }
{ "or":  [ <leaf|group>, ... ] }
```

- `and` = every child true; `or` = at least one true.
- A group has `and` OR `or` (not both at one level).
- Cap nesting at two levels (enforced by backend_v1).

## Canonical JSON shapes

Existence check (null-until-set flag):

```json
"when": { "var": "identity_confirmed", "op": "EXISTS" }
```

String comparison:

```json
"when": { "var": "is_employed", "op": "EQUALS", "value": "true" }
```

AND group:

```json
"when": { "and": [
  { "var": "is_employed", "op": "EQUALS", "value": "true" },
  { "var": "has_epf", "op": "EXISTS" }
] }
```

OR group:

```json
"when": { "or": [
  { "var": "callback_time", "op": "EXISTS" },
  { "var": "wants_to_end", "op": "EXISTS" }
] }
```

AI-judged transition with cue:

```json
{
  "when_llm": "Customer agrees to continue.",
  "go_to": "next_step",
  "deterministic_exit_cue": {
    "en-IN": "Great, let's continue.",
    "hi-IN": "बढ़िया, चलिए आगे बढ़ते हैं।"
  }
}
```

Terminal scenario (no outgoing transitions):

```json
"final_scenario": {
  "type": "single_prompt",
  "prompt": "...",
  "extract": {},
  "transitions": [],
  "tools": []
}
```

## Validation limits summary

| Constraint | Limit | Enforced by |
|---|---|---|
| Identifier regex | `^[a-z][a-z0-9_]{2,63}$` | FE + backend_v1 |
| global_prompt field max chars | 3000 (excl. newlines) | backend_v1 |
| Variable description max | 256 chars | FE + backend_v1 |
| Max variables | 100 | FE + backend_v1 |
| `when` nesting depth | 2 levels | backend_v1 |
| `when` leaves per group | 10 | backend_v1 |
| Scenario prompt min | 1 char | backend_v1 |
| `when_llm` min | 1 non-whitespace char | backend_v1 |
| `go_to` min | 1 char | FE + backend_v1 |
