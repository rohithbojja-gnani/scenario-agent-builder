# Validation: editor, save-time validator and runtime

A version 2 config passes three layers. Write for the strictest rule of all three. State of the rules: October 2026.

| Layer | When | On failure |
|---|---|---|
| Editor | "Validate" and "Save" in the bot builder | Shows the first error; Save stays disabled |
| Save-time validator (platform backend) | Every save, import and promote | The save or promote is rejected (HTTP 400). Warnings don't block |
| Runtime | When a call loads the config | The call runs as a single-prompt bot on a flattened prompt (global prompt sections + the start scenario's top-level text and `<say>` lines) and logs `CONFIG_INVALID` |

## 1. Save-time errors (block the save)

Reported with `code`, `message`, `path` (e.g. `scenarios.payment/if[1]/transition[2]`) and a line number inside the
scenario string. At most 50 errors and 50 warnings are returned. **A schema error stops all other checks**, so fix
schema errors first.

| Code | When | Fix |
|---|---|---|
| `SCHEMA_INVALID` | Wrong top-level keys (`name`, `type`…), `version` not the integer 2, more than 100 scenarios, a scenario string empty or over 5000 characters, more than 50 global transitions, `when_llm`/`filler` over 1000, a variable with extra keys, `allowed_values` on a non-enum (even `null`), a `system`/`user_defined` variable that isn't `text`, a global prompt core section missing or empty, a global prompt value over 3000 characters (newlines not counted), more than 100 variables, a description over 256, an invalid name | Match `references/v2_format.md` |
| `XML_MALFORMED` | A scenario string or global `filler` isn't well-formed XML (raw `&` or `<` in text, unclosed tag), or has a DOCTYPE or unknown entity | Escape or reword; use a serializer |
| `COMMENT_NOT_ALLOWED` | An XML comment or processing instruction | Remove it |
| `UNKNOWN_ELEMENT` | A tag not in the element list, e.g. `<u>`, `<b>`, `<tool_name>`, `<say lang>` from version 1 | Use only the version 2 tags |
| `UNKNOWN_ATTRIBUTE` | An attribute an element doesn't take, e.g. `signal` or `lang` on a transition, `lang` on `<say>` | Remove it |
| `MISSING_ATTRIBUTE` | `var`, `name`, `type`, `go_to`, `mode`, `lang`, `when` on `<if>`/`<elif>`, or `when` on a `variable` transition, missing or blank | Add it |
| `INVALID_ATTRIBUTE_VALUE` | `type` not `inline`/`variable`, `mode` not `llm`/`auto` | Fix the value |
| `MISPLACED_ELEMENT` | `<elif>`/`<else>` not directly after an If, `<text>` outside `<say>`/`<filler>`, loose words in `<say>`/`<filler>`, `<male>` outside `<text>`, content inside `<update>`/`<tool>`, two `<filler>`s | Move or remove |
| `VARIABLE_MISSING` | `<update var>`, `{{name}}` or a name in a `when` isn't declared (also in the greeting and end messages) | Declare it or fix the spelling |
| `SCENARIO_MISSING` | `start` or a `go_to` isn't a scenario | Fix the name |
| `SELF_TRANSITION` | A transition goes to its own scenario | Remove it |
| `TOOL_MISSING` | `<tool name>` isn't one of the bot's actions in that environment (checked even when the bot has none) | Use the exact action name, or add the action |
| `SYSTEM_VARIABLE_UPDATE` | `<update>` names a `system` variable | Never update system variables |
| `LLM_TRANSITION_WITH_WHEN` | `mode="llm"` with a `when` | Drop the `when`, or make it `variable`/`auto` |
| `AUTO_TRANSITION_UNCONDITIONAL` | `mode="auto"` with no `when`, outside any If branch | Add a `when` or put it alone in a branch |
| `WHEN_SYNTAX` | A `when` doesn't parse: unknown or lowercase operator, unquoted string, missing value or quote, a value after EXISTS, parentheses | See the grammar |
| `WHEN_MIXED_JOINERS` | Both AND and OR in one `when` | Split into nested Ifs or two transitions |
| `TOO_MANY_CONDITIONS` | More than 10 conditions in a `when` | Split |
| `CONDITION_TYPE_MISMATCH` | An operator not allowed for the type (NOT_EQUALS on a boolean, GREATER_THAN on text), a value that doesn't fit (`'true'` quoted for a boolean, text for a number, a decimal for number EQUALS, a value not in `allowed_values`) | See operators and values by type |
| `IF_NESTING` | Ifs nested more than 3 levels | Flatten |
| `PRIMARY_LANGUAGE_MISSING` | A `<say>`, `<filler>` or global `filler` has no line in the bot's first language | Add it |
| `DUPLICATE_LANGUAGE` | Two `<text>` for one language in one container | Merge |
| `VOICE_PAIR_INCOMPLETE` | `<male>` without `<female>` or the reverse, or a line mixed with them | Pair them |
| `EMPTY_LINE` | An empty `<text>`, `<male>` or `<female>` | Fill or remove |
| `VARIABLE_IN_SPOKEN_LINE` | `{{name}}` inside `<text>`, `<male>`, `<female>` or any filler | Move the value into instruction text |
| `INVALID_ALLOWED_VALUES` | Fewer than 2 or more than 10 options, an option over 64 characters, duplicates ignoring case, `<DEFAULT>`, or characters other than letters, digits, space, `_`, `-` | Fix the list, or use `text` |
| `TEMPLATE_NOT_ALLOWED` | `{% %}`, `{# #}`, a filter, spaces inside `{{ }}`, or an unclosed `{{` | Plain `{{name}}` only |
| `MARKUP_IN_GLOBAL_PROMPT` | A scenario tag in `global_prompt` or `when_llm` | Plain text there |

Also checked on save: the greeting and end messages (undeclared variables, extracted variables in them).

## 2. Save-time warnings (don't block)

| Code | When |
|---|---|
| `UNREACHABLE_SCENARIO` | No transition or interrupt leads to a scenario and it isn't `start` |
| `VARIABLE_NEVER_ASKED` | An `extracted` variable is in no `<update>` and no `when`, so it can never be captured |
| `UPDATE_WITHOUT_DESCRIPTION` | An `<update>` names a variable with an empty description |
| `EMPTY_BRANCH` | An `<if>`, `<elif>` or `<else>` with nothing in it |
| `LANGUAGE_NOT_CONFIGURED` | A `lang` that isn't a bot language (the editor treats this as an error) |

## 3. Editor checks (block Validate/Save in the bot builder)

- A greeting message; at least one scenario; non-empty scenarios ("Add content to this scenario").
- The four core global prompt sections non-empty.
- Names: 3 to 64 characters, first a letter (or Japanese), then `a-z`, digits, `_`; unique.
- `start` set and existing.
- Global transitions: a name, a `when_llm`, an existing `go_to`; filler languages are bot languages without
  repeats; **one global transition per target scenario**.
- `<say>`: non-empty, bot languages only, no repeated language.
- If/Else If: the `when` parses, the variable exists, the operator fits the type, a value is present (boolean,
  enum and number values are type-checked); **every branch non-empty**.
- Transitions: `go_to` exists and isn't the current scenario; `type` present; `mode` equals the mode its placement
  implies (inline alone in a branch → `auto`, otherwise `llm`; variable → `auto`); `llm` has no `when`; `variable`
  has a `when`.
- Variables: `user_defined` must be Text; an enum needs non-empty unique options; a description is required.
- Warnings: unused variables are **removed on save**; unreachable scenarios; duplicate prompts.

The editor does not check the character limits, tools, primary-language presence, updates of system variables,
unknown tags or raw `&`/`<` — the save-time validator does.

## 4. Runtime (call time)

The runtime re-checks structure, XML, references and conditions, but **not** the bot's languages and tools. It
ignores unknown JSON keys, reads every `system`/`user_defined` variable as text whatever its `type`, and runs each
transition by its `mode` and `when` whatever its `type`. A config that fails runs as a single prompt (see the
table above), so a config that only "works at runtime" is not good enough — it must pass the save-time validator.

## 5. Round-trip caveats (things that break when a config is edited in the bot builder)

Write configs so they survive an edit in the editor:

- **Transition fillers inside scenarios**: the editor keeps only the **first** `<text>` and saves it with
  `lang="en-IN"`. Put the **primary language first** in every `<filler>`, and re-check fillers after any edit in
  the editor (a non-English bot can fail `PRIMARY_LANGUAGE_MISSING` after such a save).
- **Plain text isn't XML-escaped on save**: a typed `&` or `<` breaks the save. Avoid both characters.
- **Condition values that look like numbers or booleans are written unquoted** whatever the variable type: avoid
  enum options such as `1`, `2`, `true`, and text conditions on numeric strings.
- **`when` values with `&`, `<`, `>` or `"` gain extra escaping on each save**: avoid those characters in values.
- **The underline button writes `<u>`**, which the validator rejects. Don't use underline.
- **Enum options**: the editor allows 1 to 50; the validator allows 2 to 10. Stay within 2 to 10.
- **Mixed AND/OR groups** in the condition builder silently become all-OR. Check conditions after editing.
- **Adjacent `<say>` blocks are merged** on load.
- **Unused variables are deleted on save**, and `{{new_name}}` typed in text auto-creates a `user_defined` text
  variable with an empty description (then `UPDATE_WITHOUT_DESCRIPTION` if updated).
- The JSON drawer omits `version`; the API always sends `version: 2`.

## 6. What changed from version 1 (common migration errors)

| Version 1 habit | Version 2 rule |
|---|---|
| `"type": "single_prompt"` objects with `prompt`, `extract`, `transitions`, `tools` | A scenario is one string; keys inside are rejected |
| `name` at the top level | Rejected |
| `<say lang="hi-IN">…</say>` | `<say><text lang="hi-IN">…</text></say>` |
| `<tool_name>x</tool_name>` and a `tools` array | `<tool name="x"/>` in the text where it applies |
| `extract: {var: "instruction"}` | `<update var="var"/>` after the instruction sentence |
| `{"var": "x", "op": "EQUALS", "value": "true"}` | `x EQUALS true` (typed, unquoted boolean) |
| `NOT_EQUALS "true"` on a flag | Booleans take EQUALS only: reorder transitions or use EXISTS |
| Nested `and`/`or` groups | One joiner per `when`; nest Ifs or duplicate transitions |
| `when_llm` on a scenario transition | `If <condition> → <transition type="inline" go_to="x" mode="llm"/>` |
| `deterministic_exit_cue` | `<filler>` inside the transition (or `filler` on a global transition) |
| `{% if %}` Jinja | `<if when="…">` or a STATE line (see `references/runtime.md`) |
| `signal` on transitions | Rejected; end the call with a closing line that ends in `\| EOC` |
| Campaign data as `system` | `user_defined`, type `text` |
| Any number of global prompt characters per section | 3000 per section; move shared rules into extra sections |
| No scenario size limit | 5000 characters per scenario string |
