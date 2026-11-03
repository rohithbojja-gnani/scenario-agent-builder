# Validation: editor, save-time validator and runtime

A version 2 config passes three layers. Write for the strictest rule of all three. State of the rules: verified against the code on 3 November 2026
(`scripts/check_v2.py` matches the save-time validator's codes on 106 cases).

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
| `SCHEMA_INVALID` | Wrong top-level keys (`name`, `type`…), `version` not the integer 2, more than 100 scenarios, an empty scenario string, more than 50 global transitions, `when_llm`/`filler` over 1000, a variable with extra keys, `allowed_values` on a non-enum (even `null`), a `system`/`user_defined` variable that isn't `text`, a global prompt core section missing or empty, a global prompt value over 3000 characters (newlines not counted), more than 100 variables, a description over 256, an invalid name | Match `references/v2_format.md` |
| `XML_MALFORMED` | A scenario string or global `filler` isn't well-formed XML (raw `&` or `<` in text, unclosed tag), or has a DOCTYPE or unknown entity | Escape or reword; use a serializer |
| `COMMENT_NOT_ALLOWED` | An XML comment or processing instruction | Remove it |
| `UNKNOWN_ELEMENT` | A tag not in the element list, e.g. `<b>`, `<note>`, `<tool_name>` from version 1 (`<u>…</u>` underline is accepted and stripped before the model; don't use it) | Use only the version 2 tags |
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
| `WHEN_SYNTAX` | A `when` doesn't parse: unknown or lowercase operator, unquoted string, missing value or quote, a value after EXISTS, an unmatched bracket, brackets deeper than 3 | See the grammar |
| `WHEN_MIXED_JOINERS` | Both AND and OR at one level of a `when` | Bracket one side, editor-safe form `(a OR b) AND (c)`, or split into nested Ifs or two transitions |
| `TOO_MANY_CONDITIONS` | More than 10 conditions in a `when` | Split |
| `CONDITION_TYPE_MISMATCH` | An operator not allowed for the type (NOT_EQUALS on a boolean, GREATER_THAN on text), a value that doesn't fit (`'true'` quoted for a boolean, text for a number, a decimal for number EQUALS, a value not in `allowed_values`) | See operators and values by type |
| `IF_NESTING` | Ifs nested more than 3 levels | Flatten |
| `PRIMARY_LANGUAGE_MISSING` | A `<say>`, `<filler>` or global `filler` has no line in the bot's first language | Add it |
| `DUPLICATE_LANGUAGE` | Two `<text>` for one language in one container | Merge |
| `VOICE_PAIR_INCOMPLETE` | `<male>` without `<female>` or the reverse, or a line mixed with them | Pair them |
| `EMPTY_LINE` | An empty `<text>`, `<male>` or `<female>` | Fill or remove |
| `VARIABLE_IN_SPOKEN_LINE` | `{{name}}` inside a `<filler>` or a global `filler` (it is allowed in `<say>` lines) | Keep fillers generic; put the value in the next scenario's line |
| `TEXT_TOO_LONG` | A scenario's text over 5000 characters (instructions + every `<say>` line in every language and voice; tags and `<filler>` text not counted), or one spoken line over 1000 | Shared rules to global sections; split the scenario |
| `LINK_NOT_ALLOWED` | `http://`, `https://`, `ftp://` or `www.` in scenario text, a spoken line or `when_llm` | Describe it ("the link we SMS you"); send it with a tool |
| `INVALID_ALLOWED_VALUES` | Fewer than 2 or more than 10 options, an option over 64 characters, duplicates ignoring case, `<DEFAULT>`, or characters other than letters, digits, space, `_`, `-` | Fix the list, or use `text` |
| `TEMPLATE_NOT_ALLOWED` | `{% %}`, `{# #}`, a filter, spaces inside `{{ }}`, or an unclosed `{{` | Plain `{{name}}` only |
| `MARKUP_IN_GLOBAL_PROMPT` | Any tag-like `<Word …>` in `global_prompt` or `when_llm`, including a `<Security Guidelines>` heading (only balanced `<u>…</u>` passes) | Plain text there; `SECURITY:` style headings |

Also checked on save: the greeting and end messages (undeclared variables, extracted variables in them). More than 50
errors end with one `MORE_ISSUES` error: fix and re-run.

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
- Warnings: unused variables are **removed on save**; unreachable scenarios; duplicate prompts; lines without
  `<male>`/`<female>` (shown as untranslated).

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
- **Enum options**: 2 to 10, and the editor only keeps options matching `^[a-zA-Z0-9 _-]+$` (it drops others on
  load) and compares condition values case-sensitively. Use Latin snake_case options and write them in `when`
  exactly as declared.
- **Mixed AND/OR groups** in the condition builder silently become all-OR. Check conditions after editing.
- **Adjacent `<say>` blocks are merged** on load.
- **Multi-value `IN`/`NOT_IN` fails** in the editor (the list is read as one value `"A, B"`): write
  `x EQUALS 'A' OR x EQUALS 'B'` (and `NOT_EQUALS … AND …` for NOT_IN).
- **Brackets**: the editor parses only one level, and only when every top-level part is bracketed:
  `(a OR b) AND (c)`, not `(a OR b) AND c`. Without brackets, one joiner per `when`.
- **A `<say>`/`<filler>` mixing paired and plain `<text>` loses the plain lines** when the editor re-saves it. Write
  `<male>` and `<female>` in every language's `<text>` (identical where the language doesn't mark gender).
- **A variable whose only use is the first operand of an `<if>`/`<elif>` `when`** (e.g. campaign data only in
  `<if when="risk_band EQUALS 'high'">`) is treated as unused, deleted on save, and the save then fails
  `VARIABLE_MISSING`. Make sure it is also used elsewhere (`{{x}}`, `<update>`, a later operand, a transition `when`).
- **Unused variables are deleted on save**, and `{{new_name}}` typed in text auto-creates a `user_defined` text
  variable with an empty description (then `UPDATE_WITHOUT_DESCRIPTION` if updated).
- The JSON drawer omits `version`; the API always sends `version: 2`.

## 6. `scripts/check_v2.py` extras

Besides the save-time codes, the checker reports:
- Editor errors: `TRANSITION_TYPE_MISMATCH` / `TRANSITION_MODE_MISMATCH` (contract placement rules), `DUPLICATE_GLOBAL_TARGET`,
  `FE_IN_LIST`, `FE_BRACKETS`, `FE_ENUM_CASE`, `FE_EMPTY_BRANCH`, `FE_MIXED_VOICES`, `FE_GLOBAL_PROMPT_BLANK`,
  `FE_VARIABLE_PRUNED`; warnings `FE_NO_VOICE_PAIRS`, `PRIMARY_NOT_FIRST`.
- Runtime warnings (`references/runtime.md`): `LINT_SAY_ONLY`, `LINT_NO_ESCAPE` (a waiting condition with no `llm`
  exit), `LINT_NO_FILLER`, `LINT_LANGUAGE_MISSING`, `LINT_STOP_WORD`, `LINT_SCENARIO_LONG` (over 2500 characters of
  uncached text per turn).

## 7. What changed from version 1 (common migration errors)

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
