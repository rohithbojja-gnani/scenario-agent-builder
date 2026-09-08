# scenario_config — Authoritative Schema

This is the platform contract for `bot_config.scenario_config`. Match it exactly. Load this before writing JSON.

## Top level: ScenarioConfig

| Field                | Type                          | Required | Notes                                                                                                                                                                             |
| -------------------- | ----------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`               | string                        | no       | Identifier for the config. Include it for the FE.                                                                                                                                 |
| `start`              | string                        | **yes**  | Key of the entry scenario. Must exist in `scenarios`.                                                                                                                             |
| `global_prompt`      | object                        | no       | Key-value pairs; keys **must be snake_case** (lowercase, underscores, 3-64 chars). Conventional keys: `persona`, `context`, `conversation_style`, `guardrails`, `language_rules`. |
| `variables_schema`   | dict[str, VariableDefinition] | no       | One entry per variable.                                                                                                                                                           |
| `global_transitions` | dict[str, GlobalTransition]   | no       | Checked every turn, before scenario transitions.                                                                                                                                  |
| `scenarios`          | dict[str, Scenario]           | **yes**  | The scenarios.                                                                                                                                                                    |

### global_prompt key rules

- Keys render as headings in the UI.
- Must match: `^[a-z][a-z0-9_]{2,63}$` (lowercase + underscores, 3-64 chars).
- **WRONG**: `conversationStyle`, `languageRules`, `FAQ` (camelCase or too short).
- **RIGHT**: `conversation_style`, `language_rules`, `faq_reference`.

## VariableDefinition

| Field         | Type                                            | Required           | Notes                          |
| ------------- | ----------------------------------------------- | ------------------ | ------------------------------ |
| `source`      | enum: `system` \| `user_defined` \| `extracted` | **yes**            | How the variable is populated. |
| `description` | string                                          | no but recommended | Human-readable description.    |

- **system**: auto-populated by the platform at call start. Must still be declared in schema.
- **user_defined**: known before the call — CRM/contact fields and fixed values.
- **extracted**: produced during the call by a scenario's `extract`.

## GlobalTransition

| Field                    | Type                     | Required | Notes                                                                   |
| ------------------------ | ------------------------ | -------- | ----------------------------------------------------------------------- |
| `when_llm`               | string                   | **yes**  | Natural-language trigger the model recognises.                          |
| `go_to`                  | string                   | **yes**  | Handler scenario key. **Must be unique across all global transitions.** |
| `deterministic_exit_cue` | dict[str,string] \| null | no       | Language-keyed cue. Must cover all bot languages when present.          |

**Constraints:**

- Global transitions are LLM-triggered only (no `when` rule-based conditions).
- **No `signal` field allowed** — the validator rejects it on global transitions.
- **Each `go_to` must be unique** — no two global transitions can point to the same scenario. Create separate handler scenarios if needed.

## Scenario

| Field         | Type                      | Required        | Notes                                                                                               |
| ------------- | ------------------------- | --------------- | --------------------------------------------------------------------------------------------------- |
| `type`        | string                    | **yes (FE)**    | Always `"single_prompt"`. Required by the frontend.                                                 |
| `prompt`      | string                    | no (default "") | Behaviour + say blocks + Jinja + `<tool_name>tool_name</tool_name>` tags.                           |
| `tools`       | array[string]             | no              | Tool names available in this scenario. Must match `<tool_name>` tags in `prompt` in name and order. |
| `extract`     | dict[str,string]          | no              | `variable_name -> extraction instruction`. Runs every turn.                                         |
| `transitions` | array[ScenarioTransition] | no              | Ordered; first match wins. Empty `[]` = terminal scenario.                                          |

### Say blocks in `prompt`

A scenario turn renders **at most one `<say>` per configured language**. Multi-sentence deterministic
lines belong inside a single `<say lang="...">` block — one `<say>` per sentence means only one of
them is spoken. Same-language blocks may only repeat across mutually exclusive Jinja branches, since
one branch renders. See `patterns.md` for examples.

### Tool attachment in scenarios

Tools are scoped per scenario. To attach tools:

1. Declare tool names in the scenario's `"tools"` array: `["search_place", "save_kundli"]`.
2. Append `<tool_name>` tags to the scenario's `prompt`: `<tool_name>search_place</tool_name> <tool_name>save_kundli</tool_name>`.
3. The names and order of `<tool_name>` tags in `prompt` must match the `"tools"` array exactly.
4. Scenarios without tools set `"tools": []` and omit `<tool_name>` tags from `prompt`.

## ScenarioTransition

| Field                    | Type                        | Required | Notes                                                             |
| ------------------------ | --------------------------- | -------- | ----------------------------------------------------------------- |
| `go_to`                  | string                      | **yes**  | Destination scenario key.                                         |
| `when`                   | TransitionCondition \| null | no       | Rule-based condition.                                             |
| `when_llm`               | string \| null              | no       | AI-judged intent trigger.                                         |
| `deterministic_exit_cue` | dict[str,string] \| null    | no       | Language-keyed cue. Should cover all bot languages.               |
| `signal`                 | string \| null              | no       | `"end_call"` / `"tta"` etc. Allowed on scenario transitions only. |

Use **exactly one** of `when` or `when_llm` per transition. Order transitions so the most specific/deterministic fire first.

## TransitionCondition (the `when` grammar)

### Leaf — TransitionConditionLeaf

| Field   | Type   | Required    | Notes                                                                                                    |
| ------- | ------ | ----------- | -------------------------------------------------------------------------------------------------------- |
| `var`   | string | **yes**     | Variable name (must exist in `variables_schema`).                                                        |
| `op`    | enum   | **yes**     | One of: `EQUALS`, `NOT_EQUALS`, `EXISTS`, `NOT_EXISTS` (uppercase only).                                 |
| `value` | string | conditional | **Required** for `EQUALS`/`NOT_EQUALS` (always a string). **Must be omitted** for `EXISTS`/`NOT_EXISTS`. |

### Operator rules (critical — most common validation errors)

| Operator     | `value` field             | Example                                                   |
| ------------ | ------------------------- | --------------------------------------------------------- |
| `EQUALS`     | Required, always a string | `{"var": "is_employed", "op": "EQUALS", "value": "true"}` |
| `NOT_EQUALS` | Required, always a string | `{"var": "status", "op": "NOT_EQUALS", "value": "done"}`  |
| `EXISTS`     | **Must not exist**        | `{"var": "callback_time", "op": "EXISTS"}`                |
| `NOT_EXISTS` | **Must not exist**        | `{"var": "callback_time", "op": "NOT_EXISTS"}`            |

**Never use**: `==`, `!=`, `exists`, `not exists` (wrong casing/spelling), `EQUALS` without value, `EXISTS` with value.

### Group — TransitionConditionGroup (recursive)

```json
{ "and": [ <leaf|group>, ... ] }
{ "or":  [ <leaf|group>, ... ] }
```

- `and` = every child true; `or` = at least one true.
- A group has `and` OR `or` (not both at one level).
- Cap nesting at two levels for readability.

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
