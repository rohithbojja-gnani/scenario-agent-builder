---
name: scenario-agent-builder
description: >
  Build or convert scenario-based voice agents in the scenario_config version 2 format (one XML-ish string per
  scenario, typed variables, one-line `when` conditions, global interrupts). Use when the user gives a
  single-prompt voice bot, a version 1 scenario_config (scenario objects with prompt/extract/transitions, Jinja,
  `<say lang>`), or a description, and asks to convert, migrate, "make it scenario based", or author a scenario
  agent, add male/female or per-language lines, or tune one for latency and prompt caching. Outputs a complete
  scenario_config that passes the bot builder, the save-time validator and the runtime.
---

# Scenario-Based Voice Agent Builder (version 2)

## Working rules

- Work in one pass in the main context. Read references as needed:
  - `references/v2_format.md` — **always, before writing JSON**.
  - `references/runtime.md` — how a turn runs; read before designing moves, fillers, state and tool use.
  - `references/conversion_playbook.md` — for any conversion (single prompt or version 1).
  - `references/patterns.md` — ready-made shapes and the anti-pattern table.
  - `references/variables.md` — choosing sources and types.
  - `references/validation.md` — every error code and editor quirk; read when fixing errors.
  - `references/languages_and_voices.md` — line selection, male/female pairs, translation style; read before
    writing any `<say>` or filler.
  - `references/v1_schema.md` — only to read a version 1 input.
- Validate offline, never through external APIs: `python3 scripts/check_v2.py <file.json> --languages <primary,other>
  --tools <actions> --greeting "<greeting>"` and fix every error; fix each warning or say why it stays. The checker
  matches the save-time validator's codes and adds editor (`FE_*`) and runtime (`LINT_*`) checks. Without Python,
  use the checklist at the end. `assets/example_emi_v2.json` is a complete bot that passes with no warnings; copy
  its shapes. After changing the checker, run `python3 scripts/test_check_v2.py`.
- **No real customer names, phone numbers, account numbers or other personal data in examples or test values**;
  use placeholders ([BANK_A], [CUSTOMER]).
- After the JSON, state assumptions in a few lines: languages and which is primary, tool names, scenarios
  split or merged, scripted lines fixed, behaviours that changed from the source, missing approved texts
  marked `[TO CONFIRM]`, and compliance points to review.

## Output

```jsonc
{
  "version": 2,
  "start": "greeting",
  "global_prompt": {"persona": "…", "context": "…", "conversation_style": "…", "guardrails": "…", "shared_rules": "…"},
  "variables_schema": {"customer_name": {"source": "user_defined", "type": "text", "description": "…"}},
  "global_transitions": {"reschedule": {"when_llm": "…", "go_to": "callback", "filler": "<text lang=\"hi-IN\">…</text><text lang=\"en-IN\">…</text>"}},
  "scenarios": {"greeting": "Ask if you are speaking with {{customer_name}}. <update var=\"identity_confirmed\"/> …"}
}
```

No `name` key. `bot_config.agent_type` is `scenario_based`. Deliver the greeting (`initial_message`) with it: the
greeting is played without the model before any scenario runs. A version 1 bot can't be switched to version 2 by
saving it: the version 2 config goes into a new agent.

## Mental model

- A scenario is **one string**: plain-text instructions plus a few tags — `<update var>` (report a variable),
  `<tool name>`, `<say>` (fixed line), `<transition>` (move), `<if>/<elif>/<else>` (branch).
- Each turn the model sees a cached head (fixed rules, global prompt sections, interrupts) and the **current
  scenario only**, with Ifs resolved, values filled in and tags turned into short instructions. It replies, then
  optionally writes a control block of reports. The runtime captures the reports and decides the move.
- On a move, the held reply is replaced by the transition's filler and the **next scenario answers the same
  customer turn**; that first reply can speak and use tools but can't report or move.
- The model sees only values that are shown (`[name]` in the head, `{{name}}` in the scenario). Show decision
  state with `<if>` or a STATE line.
- **Cost model**: the head is cached across turns and calls; the rendered scenario is re-sent uncached every turn;
  the reply is generated in full before it is spoken whenever a move is possible; every move adds a second serial
  model call. Details: `references/runtime.md` §9.

## Hard limits (a save over a limit fails)

| Item | Limit |
|---|---|
| Scenario text | **5000 characters**: instructions + every `<say>` line in every language and voice (tags and filler text not counted) |
| One spoken line | 1000 characters |
| Global prompt section | 3000 characters, newlines not counted |
| Scenarios / variables / interrupts | 100 / 100 (system included) / 50 |
| Enum options | 2 to 10, ≤ 64 characters, letters/digits/space/`_`/`-` |
| `when` | 10 conditions, one joiner (AND or OR); brackets only as `(…) AND (…)`, one level (editor) |
| If nesting | 3 levels |
| `when_llm`, global `filler` | 1000 characters |
| Description | 256 characters |

## The rules that make a version 2 config correct

1. **Shape.** Only the six top-level keys. Scenario values are strings. Global transitions are exactly
   `{when_llm, go_to, filler?}`. Core global prompt sections: `persona`, `context`, `conversation_style`,
   `guardrails`; add extra sections for shared rules.
2. **XML.** Each scenario, wrapped in `<scenario>`, is well-formed XML using only the version 2 tags and
   attributes. Avoid raw `&` and `<` in text (write "and", "before"). No comments, no links, no `<u>`.
3. **Templates.** Only `{{name}}` (no spaces, no filters, no Jinja), and only declared names. `{{name}}` is
   allowed in instruction text and `<say>` lines; **never in a `<filler>` or global `filler`**. The global prompt is
   plain text: no tag-like `<Heading>` text, no `[bracketed words]` other than variables.
4. **Variables.** `system` (the nine platform variables) and `user_defined` (campaign data) are `text`.
   `extracted` variables are typed: `boolean` flags, `enum` for 2–10 categories (never number- or boolean-looking
   options), `text` for dates, names and long code lists. Never `<update>` a system variable.
5. **Transitions.**
   - `type`, `go_to` and `mode` are always present.
   - A `variable` transition is `auto` and has a `when`.
   - An `inline` transition has no `when`.
   - An `llm` transition has no `when`; write it after the sentence that says when to take it.
   - An inline transition is `auto` **only when it is alone in an If branch**; anywhere else it is `llm`.
   - A transition never goes to its own scenario.
   - The first transition that fires, in written order, wins.
6. **Conditions.** Operators by type (booleans: EQUALS only; text: EQUALS/NOT_EQUALS; enum: EQUALS/NOT_EQUALS/
   IN/NOT_IN; numbers: comparisons; any: EXISTS/NOT_EXISTS). Quote strings, never booleans or numbers. Conditions
   on unanswered extracted variables **wait**; `<else>` means "answered, nothing matched". Editor-safe forms: enum
   values spelled exactly as declared; `x EQUALS 'a' OR x EQUALS 'b'` instead of a multi-value `IN`. A variable
   whose only use is the first operand of an `<if>`/`<elif>` is deleted by the editor on save: use it elsewhere too.
7. **Spoken lines and fillers.** One `<text>` per language, the **primary language first and always present**,
   every bot language covered, no empty lines, and **every `<text>` a `<male>` + `<female>` pair** (identical where
   the language doesn't mark the speaker's gender; the editor drops plain lines next to paired ones). Write in the
   platform's spoken style (`references/languages_and_voices.md`). Fillers: 2–6 words, natural, on every
   transition where an acknowledgement fits.
8. **Size.** Budget every scenario under ~4800 characters: shared rules go into extra global prompt sections;
   repeated WRONG/RIGHT lists are trimmed; variants become prefix + shared core; big jobs are split.
9. **Openings belong to the destination.** A scenario's first line is under "WHEN THIS SCENARIO STARTS" in that
   scenario; the scenario before it never speaks it (its reply is discarded on the move). The call's first line is
   the greeting; `start` answers the caller's reply to it and never greets again.
10. **Report outcomes on the deciding turn.** Dispositions and outcome flags are reported with the flag that
    triggers the move; a closing scenario's single reply can't report.
11. **Never instruct silence** ("emit no spoken text"); let the move replace the reply.
12. **Tools.** `<tool name>` where the tool applies, inside the branch that needs it. Call tools directly (no
    "let me check" line before them), answer from the result, put reports after the final answer, never write a
    tool call as text. Transfer to an agent by calling the transfer tool silently, never `| TTA` or a spoken
    "connecting you". Tool calls and results stay in the history. A tool inside a branch changes the tools array as
    the branch flips, which misses the prompt cache: keep it at the scenario's top level unless it must not be
    callable elsewhere.
13. **Interrupts** only for true "from anywhere" exits, one per target scenario; broad interrupts preempt scenario
    routes.
14. **Verbatim lines** are said once per call; give the short re-ask to use instead of repeating them. A `<say>`
    is shown on every turn its scenario is current: move on the answer, or guard it with `NOT_EXISTS`.
15. **Endings.** A closing line ends with `| EOC`. No `signal`. A closing scenario always has an instruction line: a
    scenario showing only `<say>` lines is spoken without the model and never ends the call. No `Note:` in spoken
    lines (it is the model's stop sequence).
16. **Latency.** Everything static (persona, facts, FAQs, style, language rules) goes in global prompt sections,
    which are cached; scenarios stay short (the checker warns past 2500 characters); descriptions are one line;
    replies are 1–2 short sentences (they are generated in full before speaking); interrupts are few; branch with
    `<if>` instead of pass-through scenarios. Don't restate the platform head (security guidelines, `| EOC` rule):
    `guardrails` holds domain and compliance rules.

## Procedure

**Single prompt → version 2**: spine and cross-cutting layer → scenarios by conversational job → interrupts →
global prompt (+ shared sections) → variables → scenario strings → size budget → validate → trace 8–10 test
inputs. Details: `references/conversion_playbook.md` §A.

**Version 1 → version 2**: map each field (playbook §B1), then fix version 1 workarounds that break in version 2
(playbook §B2: openings spoken by the previous scenario, "emit no spoken text", dispositions inside closing
scenarios, plain-text variable gates, `NOT_EQUALS true` on flags, nested and/or groups, Jinja, `<say lang>`,
`<tool_name>` tags), then budget, validate and trace.

**From a description**: confirm or assume languages (primary first), tool names, campaign variables, outcomes to
record and compliance lines; then as above.

## Pre-return checklist

1. Valid JSON; only `version` (2), `start`, `global_prompt`, `variables_schema`, `global_transitions`, `scenarios`.
2. `start` and every `go_to` are scenarios; no self-transitions; every scenario reachable; one interrupt per target.
3. Every scenario's text ≤ 5000 characters and well-formed XML with version 2 tags only; no raw `&`/`<`; no
   comments; no links.
4. Every `{{name}}`, `<update var>` and `when` name declared; no `{{name}}` in fillers.
5. Core global prompt sections present; every section ≤ 3000 characters; no tags in the global prompt or `when_llm`.
6. `system`/`user_defined` are `text`; enums have 2–10 safe options; descriptions ≤ 256 and non-empty; no system
   variable updated; no extracted variable that is never asked or tested.
7. Transitions follow the type/mode/when and placement rules; conditions use allowed operators and typed values;
   ≤ 10 conditions; one joiner per level; no multi-value `IN`; enum values as declared.
8. Every `<say>`/filler has the primary language first and every bot language, each `<text>` a male/female pair.
9. Openings in the destination scenarios; outcomes reported on deciding turns; no "say nothing" instructions;
   decision state visible (STATE line or `<if>`).
10. Tools only where used and only the bot's real action names; transfer via the tool without a spoken line.
11. Scripted lines kept word for word (fixes listed); missing approved texts marked `[TO CONFIRM]`.
12. Compliance: AI disclosure in the opening; no threats; calling windows; DND honoured; no data to third parties.
13. Greeting delivered; `start` doesn't greet again; closing scenarios aren't say-only.
14. `scripts/check_v2.py` reports 0 errors, and every remaining warning is explained.
