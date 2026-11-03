---
name: scenario-agent-builder
description: >
  Build Inya scenario-based voice agents (scenario_config version 2: XML scenario strings, typed variables,
  one-line when conditions, male/female and per-language lines). Use to convert a single-prompt bot or a v1
  scenario bot into v2, author one from scratch, edit or review an existing scenario_config, translate its spoken
  lines, fix its validation errors, or optimise it for latency and KV cache.
---

# Scenario agent builder (v2)

You produce a `scenario_config` that passes the backend (genvoice_backend_v1) and the editor (genvoice_app_frontend)
on the first save, runs on the v2 engine (genvoice_backend), and answers at least as well as the source prompt
(**parity**) with the least per-turn latency.

**Version check first.** A stored config with a `version` key is v2: follow this file. A stored config without
`version` is a v1 bot; a bot can't change version, so edit it with `references/v1/rules.md` (and stop here), or
re-author it as a new v2 bot (conversion_playbook.md, "v1 → v2 mapping"). New bots are always v2.

References (read when the step says so):
- `references/v2_format.md`: exact format, every save-time rule, limits, error code → fix. Read before writing JSON.
- `references/runtime_and_latency.md`: what the model sees each turn, the KV-cache layout, where latency goes.
- `references/languages_and_voices.md`: line selection, male/female, translation house style.
- `references/patterns.md`: tested scenario patterns and anti-patterns.
- `references/conversion_playbook.md`: decomposition method, parity trace, v1 → v2 mapping.
- `assets/example_emi_v2.json`: a complete bot that passes every check; copy its shapes.
- `scripts/validate_v2.py`: offline validator (backend rules + editor rules + runtime lints).

Work in one pass in the main context. No subagents, no external API calls.

## Steps

### 1. Inputs
Collect, in one message to the user if missing: the source prompt; bot languages with the **primary first**; voice
genders the bot may use; exact action (tool) names; campaign/CRM fields per call; greeting and ending message;
the domain (BFSI/RBI, insurance/IRDAI, health, outbound/TRAI).
**Done when** each item is known or written down as a stated assumption.

### 2. Map the source
Read the whole source (`conversion_playbook.md` steps 1-3). Sort every behaviour into exactly one home:
`global_prompt` section (static: persona, facts, FAQs, policy, style, language rules) · interrupt (can happen
anywhere and needs its own flow) · scenario (one conversational job) · `<say>` (exact wording) · guardrail.
**Done when** every sentence of the source has a home in this map, and you can name the scenario list and
the interrupt list (3-6).

### 3. Variables
`user_defined` for campaign data (always `text`), `system` for the platform's nine, `extracted` only for values
that a `when` tests or a later scenario reads, with the tightest type (`boolean`, `enum` of 2-10 snake_case
values, `number`/`decimal` only if compared, else `text`). Every variable gets a one-line description written
for the model (what, format, when to set).
**Done when** each extracted variable has a named reader (a `when` or a later scenario).

### 4. global_prompt (the cached head)
Sections in this order: `persona`, `context`, `conversation_style`, `guardrails`, then extras (`language_rules`,
`faq`, `compliance`…). Everything true on every turn goes here once; per-call data only as `{{var}}`.
`conversation_style` sets reply length (1-2 short sentences: replies are buffered, length = time to first audio)
and the voice-gender rule for gendered languages. `guardrails` holds domain/compliance rules and the transfer
rule only: the platform head already covers prompt injection, not revealing instructions, model identity and
ending with `| EOC`. AI disclosure goes in `persona` and the greeting.
**Done when** no scenario repeats a fact, FAQ or style rule, and every section is ≤ 3000 chars of plain text.

### 5. Scenarios
Write each scenario as one string, top to bottom: goal line → `<say>` if any → instructions with each
`<update>` right after the sentence that says when → `<if>` branches → exits. Rules in "Core rules" below.
The `start` scenario answers the caller's reply to the greeting; it never greets again.
**Done when** every scenario has a job, every waiting If has an `llm` escape, every move has a filler (unless its
target is a terminal that needs none), and every scenario is under ~2500 chars of text.

### 6. Spoken lines
Every `<say>`, `<filler>` and global `filler`: one `<text>` per bot language, each a `<male>` + `<female>` pair,
written in the house style (`languages_and_voices.md` §3). The pair differs only where the language marks the
speaker's gender (Hindi, Marathi, Gujarati, Punjabi, Urdu, Arabic); otherwise identical.
**Done when** every line exists in every bot language and both voices, and every first-person verb in a gendered
language has been checked.

### 7. Validate
Write the bot to a file and run
`python3 scripts/validate_v2.py bot.json --langs en-IN,hi-IN --tools a,b --greeting "…"` (a bot_config-shaped
file with `bot_language` and `initial_message` needs no flags). Fix every error. Fix every warning or state why
it stays. Without code execution, check `v2_format.md` §10 and the Core rules line by line instead.
**Done when** the validator prints `0 error(s)` and each remaining warning has a stated reason.

### 8. Parity trace
Trace 8-10 caller paths turn by turn (`conversion_playbook.md` step 7), reading each turn as the model sees it
(`runtime_and_latency.md` §2): what is shown, what can be reported, what moves, what the caller hears (a move
replaces that turn's reply with the filler).
**Done when** every path reaches a closing or transfer, no information the caller needs is spoken in a turn that
moves, and the scenario bot does at least what the source did on each path.

### 9. Deliver
1. The bot as JSON: `{"agent_type": "scenario_based", "bot_language": [...], "initial_message": "...",
   "scenario_config": {...}}`. `scenario_config` pastes into the editor's JSON view as is (or
   `overview.scenarioConfig` of `update_bot/v3`); greeting/ending go in the bot's message fields.
2. The validator result.
3. Assumptions (languages, tool names, field names) and items marked `[TO CONFIRM]`: compliance wording,
   regulatory regime, fees, timelines, any fact not in the source. Recommend Compliance review for BFSI,
   insurance, health and outbound calling.
4. The parity notes: what changed versus the source and why.

## Core rules

**Shape.** `scenario_config` = `version` (2), `start`, `global_prompt`, `variables_schema`, `global_transitions`
(`{when_llm, go_to, filler?}`), `scenarios` (name → string). Nothing else: no `name`, scenario objects,
`extract`, `tools` arrays, `deterministic_exit_cue`, `signal`, `<tool_name>`, Jinja. Names: lowercase `a-z0-9_`
(or Japanese), 3-64 chars, starting with a letter; meaningful, since the model sees scenario and exit names.

**Scenario tags.** `<update var="x"/>` · `<tool name="x"/>` · `<say>` → `<text lang>` → `<male>`/`<female>` ·
`<if when>` `<elif when>` `<else>` (directly adjacent, never empty, ≤ 3 deep) · transitions:

| Transition | Fires |
|---|---|
| `If <observable condition> → <transition type="inline" go_to="x" mode="llm"/>` | the model reports the exit |
| `<transition type="inline" go_to="x" mode="auto"/>` alone in an If branch | the branch is taken |
| `<transition type="variable" go_to="x" mode="auto" when="…"/>` | `when` holds after this turn's captures |

Optional `<filler>` inside a transition (no `{{var}}` in fillers). Escape `&` → `&amp;`, `<` → `&lt;`. No URLs, no
comments, no `<u>`. `{{var}}` is allowed in text and `<say>` lines.

**when.** `var OP value`, ops UPPERCASE: `EQUALS NOT_EQUALS GREATER_THAN GREATER_OR_EQUAL LESS_THAN LESS_OR_EQUAL
EXISTS NOT_EXISTS`. Strings `'quoted'`, numbers and `true`/`false` bare. Text (all campaign data): EQUALS/
NOT_EQUALS only; boolean: `EQUALS true|false` only. One joiner per level. Editor-safe: enum values in their
declared case; `a EQUALS 'x' OR a EQUALS 'y'` instead of `IN`; brackets one level deep with every top-level part
bracketed, `(…) AND (…)`. A variable used only as the first operand of an `<if>`/`<elif>` is deleted by the
editor on Save: reference it elsewhere too (`v2_format.md` §8a).

**Waiting.** A comparison on an unanswered `extracted` variable waits: the If shows no branch and the model is
asked for the value; it decides in the turn the answer arrives. `EXISTS`/`NOT_EXISTS` never wait. `<else>` means
answered-and-no-match; "not answered" is `NOT_EXISTS`. Every waiting If needs an `llm` escape for refusals.

**Moves.** One per turn; interrupts first, then transitions top to bottom. A move discards the reply generated in
that turn: the caller hears the filler, then the new scenario's reply (an extra serial LLM call). So information
is spoken in one turn and the exit fires on the caller's next turn; fillers are 2-6 word bridges.

**`<say>`.** Shown as SAY EXACTLY on every turn the scenario is current, so use it where the scenario moves on
the next answer, or guard it with `NOT_EXISTS`. A scenario showing only `<say>` lines is spoken without the
model: fast, but it can't end the call or catch interrupts, so never make a closing scenario say-only. Closing
scenarios: one instruction ("thank them, say goodbye and end the call"), no transitions. No `Note:` in lines (stop
sequence).

**Latency and KV cache** (`runtime_and_latency.md`). The head (fixed platform text + global_prompt + interrupts)
is cached across turns and calls; the scenario text, variable values and descriptions are re-sent uncached every
turn. So: static content in `global_prompt`, short scenarios, one-line descriptions, few interrupts, few hops
(branch with `<if>` instead of pass-through scenarios), tools only where needed and at the scenario's top level
(a changing tools array misses the cache from the first token).

**Transfer.** "Call the transfer tool" in guardrails or the scenario. No spoken "connecting you", no `| TTA` text,
no broad "anything hard → agent" interrupt. The platform adds the TTA tool every turn when transfer is set up.

**Data.** Use placeholders (`[CUSTOMER]`, `[BANK_A]`) for any real customer or deal detail in examples. If the
user pastes raw call recordings, transcripts or customer identifiers, flag it and work from de-identified text.
