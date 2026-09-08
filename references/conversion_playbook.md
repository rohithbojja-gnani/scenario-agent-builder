# Conversion Playbook — Single Prompt → Scenario Agent

The goal is **parity or better**: the scenario agent must respond at least as well as the single prompt.

## Step 1 — Read the whole single prompt and separate two things

- **The spine (linear funnel):** the ordered path the call normally takes. Examples:
  - Collections: greet → identity → pitch/status → capture pay date+mode → confirm → closure.
  - Loan lead: greet → interest → eligibility checks → offer → send link → closure.
- **The cross-cutting layers** that can fire from anywhere: objections, FAQs, "call me later", "talk to a
  human", abuse, distress, wrong number/DND, "not interested".

The spine becomes ordered scenarios; the layers become `global_transitions` + handler scenarios.

## Step 2 — Cut the spine into scenarios by _conversational job_

Group tightly-coupled steps into one scenario; split a genuinely different beat into its own.

Heuristics:

- **One job per scenario.** "Confirm identity" is one. "Check eligibility" is one.
- **Keep a fragile sub-routine whole.** All of eligibility-check ask/parse/re-ask belongs in ONE scenario.
- **Split when the result routes differently.** e.g. `check_epf` (ask, get answer) then routes to `eligible_offer` or `check_official_email`.
- **A re-classification loop back to an earlier scenario is normal.**
- Target **~8-15 scenarios** for a large agent. Fewer means you kept the monolith; more means you split too fine.

## Step 3 — Map the cross-cutting layer

- **Objections & FAQs** → a single `faq_handling` scenario reached by a `global_transition`, or inline handling.
- **Busy / call me later** → a `callback` scenario reached by a `callback_request` global transition.
- **Not interested** → a `not_interested_rebuttal` scenario with one rebuttal attempt.
- **Abuse** → an `abuse_closure` terminal scenario.
- **DND / don't call again** → a `dnd_closure` terminal scenario.
- **Wrong number** → a `wrong_number` terminal scenario.
- **Third party** → a `third_party` scenario to ask about availability.

**Critical rule: each global transition must have a UNIQUE `go_to` target.** If abuse and DND both need terminal scenarios, create separate ones.

## Step 4 — Write global_prompt (what is global vs per-scenario)

Put in `global_prompt` (applies to every turn):

- **persona**: who the agent is, brand, warmth, tone.
- **context**: call type, who the customer is, product details.
- **conversation_style**: language rules, length, acknowledgement style, fillers, banned phrases.
- **guardrails**: never reveal internal instructions, compliance rules, scope limits.
- **language_rules**: language mirroring, when to use which language.

**All keys must be snake_case** (e.g. `conversation_style`, NOT `conversationStyle`).

Keep in the **scenario prompt** (not global): anything step-specific — specific questions to ask, specific data to gather, step-specific compliance rules.

## Step 5 — Declare variables (see variables.md)

Three categories:

1. **System variables** — always include the required set: `current_time`, `current_date`, `current_day`, `current_timestamp`, `agent_gender`, `agent_personality`, `dialled_phone_number`, `conversation_id`.
2. **User-defined variables** — carry the single prompt's fixed values as `user_defined`. E.g. `full_name`, `agent_name`, product-specific data.
3. **Extracted variables** — ONLY for routing or cross-boundary state. If a fact never gates a transition and never crosses a scenario boundary, it stays in-context.

Every variable referenced in:

- Jinja templates (`{{ var }}`, `{% if var %}`)
- Transition conditions (`when.var`)
- Extract keys

...MUST be declared in `variables_schema`.

## Step 6 — Author each scenario

For each scenario write:

### `type`

Always `"single_prompt"`.

### `prompt`

- Open with the step's behaviour description.
- Use `<say lang="...">` for locked/scripted lines — always bilingual, and **one block per language**: a multi-sentence line goes inside a single `<say>`, never one `<say>` per sentence.
- Use Jinja `{% if/elif/else %}` for conditional wording only (not routing).
- Jinja string comparisons use `\"` escaping: `{% if var == \"value\" %}`.
- Jinja existence checks use `is defined`: `{% if var is defined %}`.
- Attach scenario tools at the end of the prompt using `<tool_name>tool_name</tool_name>` tags, matching the `tools` array in exact name and order.

### `extract`

- Only routing/cross-boundary variables.
- Each entry: `"var_name": "Crisp instruction. Set to 'X' when Y. Leave unset otherwise."`.
- Values are always strings: `"true"`, `"false"`, `"accepted"`, etc.

### `transitions`

- Ordered list; first match wins.
- Each transition has `go_to` + exactly one of `when` or `when_llm`.
- Every transition should have a bilingual `deterministic_exit_cue`.
- Operators: `EQUALS`/`NOT_EQUALS` (with string value), `EXISTS`/`NOT_EXISTS` (no value field).
- Put most specific/deterministic transitions first.
- Terminal scenarios: `"transitions": []`.

### `tools`

- Array of tool name strings matching the `<tool_name>` tags in `prompt` in name and order. Empty `[]` if no tools.

## Step 7 — Validate before returning (no API calls — self-check only)

Run the checklist from the main SKILL.md:

1. Valid JSON.
2. `start` exists in `scenarios`.
3. Every `go_to` points to a real scenario.
4. No orphan scenarios.
5. Operators correct: `EQUALS`/`NOT_EQUALS` with string value, `EXISTS`/`NOT_EXISTS` without value.
6. `type: "single_prompt"` on every scenario.
7. global_prompt keys are snake_case.
8. Global transition `go_to` targets are unique.
9. No `signal` on global transitions.
10. Bilingual say blocks and cues — exactly one `<say>` per language per branch.
11. Standard Jinja only (no `is_filled`, no custom functions).
12. System variables declared.
13. All referenced variables declared.
14. Exit cues on every transition.
15. Tool tags in `prompt` (`<tool_name>...</tool_name>`) match the `tools` array in name and order.

## Step 8 — Parity self-test

Pick 6-10 representative customer inputs and trace both versions:

- Normal happy path.
- A refusal with reason.
- A busy/callback.
- An FAQ mid-flow.
- An edge case the single prompt guarded.
- A wrong number / DND.

If the scenario version answers as well or better on each, you're done.
