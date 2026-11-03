# scenario_config v2: exact format and every save-time rule

Sources: `genvoice_backend/docs/backend_contract.md` (the contract), `genvoice_backend_v1/main/scenario_v2/*`
(the save/promote validator, the strictest gate), `genvoice_backend/src/scenario_based/v2/config.py` (the
runtime compiler). Where they differ, this file follows the strictest one. `scripts/validate_v2.py` checks all of it.

## 1. Where it lives

```jsonc
// bot_config
{ "agent_type": "scenario_based",
  "scenario_config": {
    "version": 2,                 // the number 2. Its presence is what makes a config v2
    "start": "greeting",          // a key of scenarios
    "global_prompt": {...},       // §3
    "variables_schema": {...},    // §4
    "global_transitions": {...},  // §5
    "scenarios": {"greeting": "<one XML-tagged string>"}  // §6
  } }
```

- Those six keys only. No `name`, no `type` on scenarios, no `signal`, no `tools` array, no
  `deterministic_exit_cue` (all v1 or runtime-only; `SCHEMA_INVALID`).
- Saved via `POST /genbots/dashboard/write/update_bot/v3` as `overview.scenarioConfig` (snake_case keys, sent as
  is), with `overview.greetingMessage`/`endingMessage`. Dry-run: `POST /genbots/bot-config/validate` with
  `{bot_id, environment, scenarioConfig, greetingMessage, endingMessage, languages}` (`languages` omitted → the
  bot's stored `bot_language`). The editor only lets you Save after a passing Validate.
- Pasting into the editor's JSON view: the same object; `version` may be omitted there (added on the API call).
- A bot keeps its version for life: v2 can't be saved on a v1 bot and vice versa. New scenario bots are v2.
- After a save, live calls may use the old config for up to 5 minutes (bot cache).

## 2. Names

Scenario keys, variable keys, global transition keys, `start`, every `go_to`, extra `global_prompt` keys:

`^[a-z぀-ゟ゠-ヿ一-鿿][a-z0-9_぀-ゟ゠-ヿ一-鿿]{2,63}$`

Lowercase Latin, digits, `_`, Japanese; 3-64 chars; starts with a letter. `ab`, `Greeting`, `step-2`, `2nd` fail.

## 3. global_prompt

| Rule | Detail |
|---|---|
| Required, non-blank | `persona`, `context`, `conversation_style`, `guardrails` (backend also accepts `conversationStyle`; the editor writes `conversation_style` and puts these four first, so use that order) |
| Extra sections | Allowed; key follows §2 (e.g. `language_rules`, `faq`, `compliance`) |
| Length | 3000 chars per section, newlines not counted |
| Plain text only | No tag-like `<Word>` at all, not even a `<Security Guidelines>` heading (`MARKUP_IN_GLOBAL_PROMPT`). Use `SECURITY GUIDELINES:` |
| Templates | Only `{{name}}` of a declared variable. No `{% %}`, `{# #}`, filters, spaces inside braces |
| Order | Sections are shown to the model in stored order, every turn, in the cached head |

Each `{{name}}` in the global prompt reaches the model as the literal `[name]`; its value is sent in the per-turn
VARIABLE VALUES block instead, so the head stays byte-identical across calls (see `runtime_and_latency.md`).

## 4. variables_schema

```json
"payment_mode": {"source": "extracted", "type": "enum", "allowed_values": ["UPI", "Net banking", "Cash"],
                 "description": "How the customer wants to pay."}
```

| Field | Rule |
|---|---|
| `source` | `system` \| `user_defined` \| `extracted` |
| `type` | Required. `text` \| `number` \| `decimal` \| `boolean` \| `enum`. `system` and `user_defined` are always `text` |
| `description` | String, max 256. Optional in the schema but required by the variable API and shown to the model on every ask: always write one |
| `allowed_values` | `enum` only (present and non-null), absent on every other type. 2-10 values, unique ignoring case, each 1-64 chars. Backend allows letters of any script; **the editor only `^[a-zA-Z0-9 _-]+$`** (it silently drops others on load), so use Latin letters, digits, spaces, `_`, `-`. No commas, dots, slashes, brackets, `<DEFAULT>`. Prefer short snake_case values (`net_banking`): they appear in every ask hint and capture |
| Count | Max 100 variables including the 9 system ones |
| Extra fields | None (`SCHEMA_INVALID`) |

System variables (the backend adds any missing ones on save, typed `text`; declare the ones you reference):
`agent_name`, `agent_gender`, `agent_personality`, `current_time`, `current_date`, `current_day`,
`current_timestamp`, `dialled_phone_number`, `conversation_id`. They never change in a call; `<update>` on one is
`SYSTEM_VARIABLE_UPDATE`.

What the model is asked for, and what is stored:

| Type | Model sees | Captured when | Stored |
|---|---|---|---|
| `text` | `<text>` | non-empty, not null-like (`null`, `unknown`) | trimmed text |
| `number` | `<whole number>` | digits, optional `-`; commas/spaces ignored; `.0` ok, other decimals rejected | `100000` |
| `decimal` | `<decimal number>` | digits, optional `-`, at most one `.` | `7.5` |
| `boolean` | `<true or false>` | `true`/`false` any case. `yes`/`no` rejected | `true` |
| `enum` | `<one of: A, B, C>` | exactly one allowed value, any case | the declared spelling |

An unset variable holds `<DEFAULT>`, never `false`/`0`/`""`. A value that doesn't fit the type is dropped, so the
condition keeps waiting.

## 5. global_transitions (interrupts)

```json
"talk_to_human": {"when_llm": "The customer asks to speak to a human agent.", "go_to": "agent_handoff",
                  "filler": "<text lang=\"en-IN\">Sure.</text><text lang=\"hi-IN\">जी, ज़रूर।</text>"}
```

- Keys: `when_llm` (required, 1-1000 chars, plain text: no tags, no links, only declared `{{name}}`), `go_to`
  (required scenario), `filler` (optional string of `<text>` elements, same line rules as §6.5, **no `{{name}}`**).
- Max 50. Shown in the cached head on every turn, so each costs tokens on every request: keep them few and short.
- Checked before scenario transitions. A reported interrupt that leads to the current scenario is ignored.
- No uniqueness rule on `go_to` in v2 (that was v1).

## 6. Scenario strings

A scenario is ONE string: plain-text instructions plus the tags below. Wrapped in `<scenario>…</scenario>` it must
be well-formed XML.

### 6.1 Escaping and forbidden markup

- In text: `&` → `&amp;`, `<` → `&lt;` (`T&C`, `amount < 1000` are `XML_MALFORMED`). `>` is fine.
- Only the 5 XML entities (`&amp; &lt; &gt; &quot; &apos;`). `&nbsp;` etc. → `XML_MALFORMED`.
- No comments `<!-- -->`, no `<?…?>`, no DOCTYPE, no CDATA tricks.
- In JSON, attribute quotes are `\"`; use single quotes for string values inside `when`:
  `"<if when=\"city EQUALS 'Mumbai'\">…</if>"`.
- No links anywhere in scenario text or lines (`http://`, `https://`, `ftp://`, `www.`): `LINK_NOT_ALLOWED`.
- Templates: only `{{name}}` of a declared variable. Unset → renders as nothing, so word the sentence to survive
  that, or guard it with `<if when="name EXISTS">`.
- Never emit `<u>…</u>`: it is an editor underline, stripped before the model sees it.

### 6.2 Elements

| Element | Attributes | Content | Where |
|---|---|---|---|
| `<update var="x"/>` | `var` | empty | body |
| `<tool name="x"/>` | `name` (a bot action, `TOOL_MISSING` otherwise) | empty | body |
| `<say>` | none | one or more `<text>` | body |
| `<transition .../>` | `type`, `go_to`, `mode`, `when` (variable only) | empty or one `<filler>` | body |
| `<filler>` | none | one or more `<text>` | inside `<transition>` only |
| `<text lang="xx-YY">` | `lang` | a line, or exactly one `<male>` + one `<female>` | inside `<say>`/`<filler>`/global `filler` |
| `<male>`, `<female>` | none | a line | inside `<text>` |
| `<if when>`, `<elif when>` | `when` | a body | body; `<elif>` directly after `</if>`/`</elif>` |
| `<else>` | none | a body | directly after `</if>`/`</elif>` |

"Directly after" = only whitespace between. A sentence between `</if>` and `<else>` is `MISPLACED_ELEMENT`.
A body holds everything a scenario can (text, `{{name}}`, update, tool, say, transition, nested If). If nesting
max 3 levels. Any other tag or attribute: `UNKNOWN_ELEMENT` / `UNKNOWN_ATTRIBUTE`. Never leave a branch body
empty (backend warns, the editor blocks Save). Attribute values in double quotes (the editor's convention;
`when` strings use single quotes inside).

### 6.3 `<update var>`

Renders as `→ report @x=<type hint> (description)` where it stands. The sentence around it says when to capture:
`If they agree → <update var="consent"/>`. Updating a `user_defined` variable is allowed (customer corrects
campaign data). A capture is kept only if the variable was asked for or tested this turn.

### 6.4 Transitions

| Written | Moves when | Rules |
|---|---|---|
| `<transition type="inline" go_to="x" mode="llm"/>` in text | the model reports `[exit: x]` this turn (shown at turn start and still shown) | no `when` |
| `<transition type="inline" go_to="x" mode="auto"/>` **alone** in an `<if>/<elif>/<else>` | that branch is taken | no `when`; nothing else in the branch except its own `<filler>` |
| `<transition type="variable" go_to="x" mode="auto" when="…"/>` anywhere | `when` holds after this turn's captures | `when` required |

Errors: `mode="auto"` with no `when` outside a branch (`AUTO_TRANSITION_UNCONDITIONAL`); `mode="llm"` with `when`
(`LLM_TRANSITION_WITH_WHEN`); `type="variable"` without `when`; `type="inline"` with `when`; inline `auto` next to
other content in a branch (the auto move would swallow that content) or inline `llm` alone in a branch
(`TRANSITION_MODE_MISMATCH`); `go_to` = own scenario (`SELF_TRANSITION`); missing `type`/`go_to`/`mode`.

Order and priority each turn: interrupts first, then the first firing transition top-to-bottom, one move per
turn. After a move the new scenario answers the same utterance (recall step); its own transitions are judged
next turn. A `<filler>` is spoken the moment the move happens, in place of the old scenario's reply.

### 6.5 Spoken lines (`<say>`, `<filler>`, global `filler`)

- `<say>` = said word for word. All words inside `<text lang>`; bare words in `<say>` are `MISPLACED_ELEMENT`.
- One `<text>` per language (`DUPLICATE_LANGUAGE`). The bot's **primary** language (first in its language list)
  is required in every `<say>`/`<filler>`/global `filler` (`PRIMARY_LANGUAGE_MISSING`). Other bot languages are
  optional for the validator, but **always write all of them**: a missing language falls back to the primary
  language's line mid-call. A `lang` the bot doesn't have is a warning.
- `<text>` holds plain words OR exactly one `<male>` and one `<female>`, never words plus voices
  (`VOICE_PAIR_INCOMPLETE`). No empty lines (`EMPTY_LINE`).
- **Editor rule: pair every language.** If one `<text>` in a `<say>`/`<filler>` has `<male>`/`<female>`, the
  editor drops the plain `<text>` of the other languages when it re-saves; and plain-only lines are flagged as
  untranslated. So write `<male>` and `<female>` in **every** `<text>`, identical where the language doesn't mark
  the speaker's gender. Runtime cost is zero (only the picked line is rendered); it only counts toward the 5000
  scenario chars.
- `{{name}}` allowed in `<say>` lines; **not** in `<filler>` or global `filler` (`VARIABLE_IN_SPOKEN_LINE`).
- One line ≤ 1000 chars. Language/voice choice: `languages_and_voices.md`.

### 6.6 If / Else If / Else and "waiting"

- First true branch wins; `<else>` only when every branch is answered and false. Only the taken branch's body is
  shown; the model never sees the conditions.
- A condition on an `extracted` variable with no value **waits**; on `system`/`user_defined` with no value it is
  false; `EXISTS`/`NOT_EXISTS` always decide. AND is false if any part is false, OR true if any part is true,
  otherwise waits.
- While an If waits, none of its branches is shown and the model is asked to report the missing variables (even
  without an `<update>`). It is decided in the same turn the answer is captured; an `auto` transition in the
  taken branch moves immediately (its filler replaces the reply).
- To act on "not answered yet" use `x NOT_EXISTS`, never `<else>`.
- A waiting If keeps asking forever: always pair it with an `llm` exit for refusal/unknown.

## 7. `when` conditions

```
when       = part { "AND" part } | part { "OR" part }     -- one joiner per level
part       = condition | "(" when ")"                      -- brackets ≤ 3 deep
condition  = name OPERATOR [ value ]
value      = 'string' | number | true | false | ('a', 'b')
```

- Operators UPPERCASE: `EQUALS NOT_EQUALS GREATER_THAN GREATER_OR_EQUAL LESS_THAN LESS_OR_EQUAL IN NOT_IN EXISTS
  NOT_EXISTS`. `AND`/`OR` uppercase, `true`/`false` lowercase. No `==`, `<`, `CONTAINS`.
- Strings in single quotes, `'` escaped as `''` (`'O''Brien'`). Lists: `('UPI', 'Cash')` of quoted strings.
- Mixing AND and OR at one level is `WHEN_MIXED_JOINERS`: write `(a AND b) OR c`. Max 10 conditions per `when`.
- Text/enum compare ignoring case and surrounding spaces at runtime; numbers compare as numbers.
- **Editor-safe subset** (the editor's parser is narrower than the grammar; it blocks Validate otherwise):
  - Enum values written exactly as declared (case-sensitive in the editor).
  - No multi-value `IN`/`NOT_IN` (the editor reads the list as one value): write
    `mode EQUALS 'upi' OR mode EQUALS 'cash'`, and `mode NOT_EQUALS 'upi' AND mode NOT_EQUALS 'cash'`.
  - Brackets one level deep only, and then every top-level part bracketed:
    `(a EQUALS 'x' OR a EQUALS 'y') AND (b EQUALS true)`, not `(…) AND b EQUALS true`.

| Type | Operators | Value |
|---|---|---|
| `text` (incl. every system/user_defined) | EQUALS, NOT_EQUALS | `'quoted'` |
| `number` | EQUALS, NOT_EQUALS (whole numbers), GREATER_*, LESS_* (decimals ok) | bare number |
| `decimal` | same six | bare number |
| `boolean` | EQUALS only | bare `true`/`false` (`NOT_EQUALS true` → write `EQUALS false`) |
| `enum` | EQUALS, NOT_EQUALS, IN, NOT_IN | an allowed value / list of allowed values |
| any | EXISTS, NOT_EXISTS | none |

Campaign data is text, so `emi_amount GREATER_THAN 4000` is invalid: capture a numeric copy as an `extracted`
`number` if you must compare, or branch on a precomputed `user_defined` flag (`risk_band EQUALS 'high'`).

## 8. Greeting and ending messages

`initial_message` / `end_message` live outside `scenario_config` but are validated with it: every `{{name}}` must be
declared and must not be `extracted` (empty at call start). The editor requires a greeting. The greeting is spoken
before any scenario runs (no LLM), so `start` handles the caller's reply to it (`runtime_and_latency.md` §1).

## 8a. Known editor bug: variables pruned on Save

On header Save the editor deletes variables it thinks are unused. Its check doesn't see a variable whose only use
is the **first operand of an `<if>`/`<elif>` `when`** (e.g. `user_defined` campaign fields used only in
`<if when="risk_band EQUALS 'high'">`). The save then fails with `VARIABLE_MISSING`. `<update var>`, `{{x}}`,
transition `when`s and non-first operands are seen. Until the editor is fixed: make sure such a variable also
appears as `{{x}}`, in an `<update>`, or as a later operand; or start that `when` with a space
(`when=" risk_band EQUALS 'high'"`, valid for the backend; survives JSON paste, not re-saves from the visual editor).
`validate_v2.py` reports it as `FE_VARIABLE_PRUNED`.

## 9. Limits

| Limit | Value |
|---|---|
| Scenarios / global transitions / variables | 100 / 50 / 100 (system included) |
| global_prompt section | 3000 chars, newlines free |
| Scenario text | 5000 chars: instructions + every `<say>` line in every language and voice. Tags and `<filler>` text not counted |
| One spoken line | 1000 chars |
| `when_llm` | 1000 chars |
| Variable description | 256 chars |
| Enum | 2-10 values, ≤ 64 chars each |
| If nesting / when brackets / conditions per when | 3 / 3 / 10 |
| Validator report | first 50 errors (+`MORE_ISSUES`) |

## 10. Error code → fix

| Code | Usual cause → fix |
|---|---|
| `SCHEMA_INVALID` | extra key (`name`, `signal`, `deterministic_exit_cue`, scenario as object), bad name, non-text system/user_defined, enum without `allowed_values`, section > 3000, `version` not 2 |
| `XML_MALFORMED` | bare `&` or `<` in text, unclosed tag, `&nbsp;` |
| `UNKNOWN_ELEMENT` / `UNKNOWN_ATTRIBUTE` | `<note>`, `<b>`, `<tool_name>`, `signal=`, `lang=` on `<say>` |
| `MISSING_ATTRIBUTE` / `INVALID_ATTRIBUTE_VALUE` | transition without `type`/`go_to`/`mode`; `type="llm"`; `mode="maybe"`; `<if>` without `when` |
| `MISPLACED_ELEMENT` | words directly in `<say>`; `<text>` in body; `<else>` after a sentence; content inside `<update>`/`<tool>`; two fillers |
| `COMMENT_NOT_ALLOWED` | `<!-- -->`, `<?…?>` |
| `VARIABLE_MISSING` / `SCENARIO_MISSING` / `TOOL_MISSING` | typo or undeclared name; tool not an action of this bot in this environment |
| `SYSTEM_VARIABLE_UPDATE` | `<update var="current_date"/>` |
| `LLM_TRANSITION_WITH_WHEN`, `AUTO_TRANSITION_UNCONDITIONAL`, `TRANSITION_TYPE_MISMATCH`, `TRANSITION_MODE_MISMATCH`, `SELF_TRANSITION` | see §6.4 |
| `WHEN_SYNTAX` / `WHEN_MIXED_JOINERS` / `TOO_MANY_CONDITIONS` | §7 |
| `CONDITION_TYPE_MISMATCH` | operator not allowed for the type; `'true'` quoted; number in quotes; value not in `allowed_values`; `IN 'x'` without list |
| `IF_NESTING` | 4+ nested Ifs: split into another scenario |
| `PRIMARY_LANGUAGE_MISSING` / `DUPLICATE_LANGUAGE` / `VOICE_PAIR_INCOMPLETE` / `EMPTY_LINE` | §6.5 |
| `VARIABLE_IN_SPOKEN_LINE` | `{{x}}` in a `<filler>` or global `filler` |
| `TEXT_TOO_LONG` | scenario > 5000 or line > 1000: split the scenario, move shared text to `global_prompt` |
| `LINK_NOT_ALLOWED` | a URL: describe it ("the link we send by SMS") or send it via a tool |
| `INVALID_ALLOWED_VALUES` | < 2 or > 10 options, duplicates, punctuation in an option |
| `TEMPLATE_NOT_ALLOWED` | Jinja `{% if %}`, `{{ x|upper }}`, `{{ x }}` with spaces |
| `MARKUP_IN_GLOBAL_PROMPT` | any `<Tag>` in `global_prompt` or `when_llm` |
| `INITIAL_MESSAGE_EXTRACTED_VAR` | greeting/ending uses an extracted variable |

Warnings (save anyway, but fix): `UPDATE_WITHOUT_DESCRIPTION`, `VARIABLE_NEVER_ASKED` (extracted var never in an
`<update>` or `when`), `UNREACHABLE_SCENARIO`, `EMPTY_BRANCH`, `LANGUAGE_NOT_CONFIGURED`.

`validate_v2.py` extras: `FE_*` = editor blocks or damages it (`FE_IN_LIST`, `FE_BRACKETS`, `FE_ENUM_CASE`,
`FE_EMPTY_BRANCH`, `FE_MIXED_VOICES`, `FE_GLOBAL_PROMPT_BLANK`, `FE_VARIABLE_PRUNED` are errors;
`FE_NO_VOICE_PAIRS` warns); `LINT_*` = runtime/latency warnings (`LINT_SAY_ONLY`, `LINT_NO_ESCAPE`,
`LINT_NO_FILLER`, `LINT_LANGUAGE_MISSING`, `LINT_STOP_WORD`, `LINT_SCENARIO_LONG`).
