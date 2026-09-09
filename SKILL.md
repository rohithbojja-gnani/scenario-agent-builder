---
name: scenario-agent-builder
description: >
  Convert a single-prompt voice agent into a scenario-based agent JSON, or author one from scratch.
  Use whenever the user provides a single-prompt voice bot and asks to migrate, convert, or
  "make it scenario based"; or asks to design a scenario_config JSON with global_prompt,
  global_transitions, scenarios, transitions, say blocks, extracted variables, etc.
  Outputs a complete, validator-safe scenario_config JSON.
---

# Scenario-Based Voice Agent Builder

## IMPORTANT: Agent efficiency rules

This skill must execute with **minimal resource usage**:

- **Do NOT spawn subagents or use the Task tool.** Perform the entire conversion in a single pass within the main agent context.
- **Read reference files selectively.** Always read `references/schema.md` before writing JSON. Read `references/conversion_playbook.md` only for complex single-prompt-to-scenario conversions. Read `references/variables.md` and `references/patterns.md` only when the conversion involves unfamiliar variable patterns or say-block structures.
- **Do NOT call external APIs** to validate the generated JSON. Use only the self-validation checklist in this file.
- **Output the JSON in one shot.** Do not iterate through multiple drafts or verification passes with tool calls.

---

## What this does

Turns a **single giant prompt** voice agent into the **scenario-based framework**: many small reactive
scenarios the platform connects, instead of one prompt carrying all the routing. The conversion must be
**parity-or-better** -- the scenario agent must respond at least as well as the single prompt.

Reference files (read selectively, not all at once):
- `references/schema.md` -- the authoritative `scenario_config` JSON schema. **Load before writing any JSON.**
- `references/conversion_playbook.md` -- step-by-step method to decompose a single prompt into scenarios.
- `references/variables.md` -- canonical variable names, sources, system variables, and the "minimal extracted variables" rule.
- `references/patterns.md` -- say blocks, Jinja, cues, global transitions, and anti-patterns from real migrations.

---

## Tool context: ask for bot_config when available

When the user provides or can provide the full `bot_config` (including the `actions` array listing all available tools), **ask for it** or include it in context. This enables:
- Correct per-scenario tool scoping using `<tool_name>` tags.
- Validation that tool names in `tools` arrays actually exist in the bot's action catalog.
- Proper `<tool_name>` tag placement at the end of scenario prompts.

Without the bot_config tool list, the skill cannot verify tool names. In that case, use whatever tool names the user provides or mentions in the single prompt, and note the assumption.

---

## The mental model

An agent = **one building block, the scenario**. A scenario is reactive: it generates output in response to
the customer's turn. The FDE authors *what a scenario says and decides*; the **platform owns** how scenarios
connect and how the call runs.

Top-level object (`scenario_config`):
- `name` (string) -- identifier for the config. Required by the FE.
- `start` (string, required) -- the entry scenario key. Must be a valid identifier.
- `global_prompt` (object) -- persona / context / conversation_style / guardrails, applied to every scenario. **Keys must be snake_case** (lowercase + underscores, 3-64 chars).
- `variables_schema` (dict) -- each var has a `source`: `system` | `user_defined` | `extracted`, plus a `description`.
- `global_transitions` (dict) -- cross-cutting handlers checked every turn before scenario transitions.
- `scenarios` (dict) -- the scenarios; each has `type`, `prompt`, optional `tools`, `extract`, `transitions`.

---

## Validation limits quick-reference

These limits are enforced by both the FE and backend_v1. Violating any of them causes a validation error.

| Constraint | Limit | Notes |
|---|---|---|
| Identifier regex | `^[a-z][a-z0-9_]{2,63}$` | Applies to: scenario keys, variable names, global transition names, extra global_prompt keys. Must start with lowercase letter. |
| Identifier length | 3-64 chars | Too short (1-2 chars) or too long (65+) rejected. |
| global_prompt field values | max 3000 chars | Newlines (`\n`, `\r`) excluded from count. |
| Variable description | max 256 chars | Empty string allowed but description recommended. |
| Max variables total | 100 | Includes system + user_defined + extracted. |
| `when` condition nesting | max 2 levels | `and`/`or` group depth. |
| `when` condition leaves | max 10 per group | Leaves per single `and`/`or` array. |
| Scenario prompt | min 1 char | Non-empty required by backend_v1. No max length. |
| `when_llm` text | min 1 non-whitespace char | Blank/whitespace-only rejected. No max length. |
| `go_to` | min 1 char | Non-empty string required. |

---

## The rules that make a conversion correct (learned from real migrations)

### Rule 1: Operator spelling and value rules

The platform accepts these four operators in **UPPERCASE** only:

| Operator | Spelling in JSON | `value` field |
|---|---|---|
| Equals | `"EQUALS"` | Required. Always a **string** (e.g. `"true"`, `"false"`, `"accepted"`). |
| Not equals | `"NOT_EQUALS"` | Required. Always a **string**. |
| Exists | `"EXISTS"` | **Must be `null` or omitted entirely.** FE sends `null`; backend_v1 requires `null` or absent. Never set to a string. |
| Not exists | `"NOT_EXISTS"` | **Must be `null` or omitted entirely.** Same rule as EXISTS. |

Never use `==`, `!=`, `exists`, `not exists` (wrong casing), `EQUALS` with no value, or `EXISTS` with a non-null value.

### Rule 2: Every scenario needs `"type": "single_prompt"`

The frontend requires this field on every scenario object. Always include it. The backend_v1 defaults it, but omitting causes FE errors.

### Rule 3: global_prompt -- required fields and snake_case keys

**Required fields** (must be non-empty after trim):
- `persona` -- who the agent is, brand, warmth, tone.
- `context` -- call type, who the customer is, product details.
- `conversation_style` -- language rules, length, acknowledgement style, fillers, banned phrases.
- `guardrails` -- never reveal internal instructions, compliance rules, scope limits.

**Optional extra keys** (e.g. `language_rules`, `faq_reference`) are allowed but must also follow the identifier rules.

**All keys** must be snake_case: lowercase letters, digits, and underscores only, 3-64 characters. Must match `^[a-z][a-z0-9_]{2,63}$`.
- **WRONG**: `conversationStyle`, `languageRules`, `FAQ` (camelCase, uppercase, or too short).
- **RIGHT**: `conversation_style`, `language_rules`, `faq_reference`.

**Max value length**: each field value max 3000 characters (newlines excluded from count).

### Rule 4: Unique go_to targets for global transitions

Each global transition must point to a **different** scenario. The backend_v1 validator raises `DUPLICATE_GOTO` if two global transitions share the same `go_to`. If `abuse` and `dnd_request` both need to end the call, create separate terminal scenarios for each (e.g. `abuse_closure` and `dnd_closure`).

This uniqueness is enforced **within** global_transitions only, not cross-scope with scenario transitions.

### Rule 5: No `signal` field in authored JSON

The `signal` field (e.g. `"signal": "end_call"`, `"signal": "tta"`) is a **runtime-only** concept in the `genvoice_backend` runtime engine. It does **not** exist in the FE or backend_v1 authoring schema:
- The FE has no `signal` field anywhere in scenario config validation.
- The backend_v1 `ScenarioTransition` and `GlobalTransition` models use `extra="forbid"`, so adding `signal` causes a Pydantic validation error.

**Do not include `signal` in authored scenario_config JSON** unless the user explicitly says the config will be consumed directly by the runtime engine (not through the FE/backend_v1 authoring pipeline).

If the user asks about signals: the runtime engine (`genvoice_backend`) supports `signal` on both scenario transitions and global transitions. Known runtime signal values include: `end_call`, `TTA` (transfer to agent), `EOC`, `HOLD`, `VBV`, `VBE`. But these are resolved at runtime only and should not appear in FE-authored configs.

### Rule 6: All say blocks and cues must cover all configured languages

If the bot supports `["en-IN", "hi-IN"]`, then every `<say>` block must have both `lang="en-IN"` and `lang="hi-IN"` variants, and every `deterministic_exit_cue` must have both `"en-IN"` and `"hi-IN"` keys. Mismatched languages cause validation errors.

Additional say-block rules (backend_v1):
- Say tags must be balanced (every `<say>` has a `</say>`), no nesting or overlap.
- Adjacent `<say>` tags (only whitespace between) must use **different** `lang` values.
- The primary agent language (first in the languages list) must appear in say tags if any say tags exist.

### Rule 7: Jinja must use standard syntax only

The platform's Jinja validator does NOT have custom functions like `is_filled()`. Use only standard Jinja2:

| Check | Jinja syntax | Notes |
|---|---|---|
| Variable exists | `{% if var is defined %}` | No RHS, no escaping needed |
| Variable missing | `{% if var is not defined %}` | No RHS |
| Equals a string | `{% if var == \"value\" %}` | `\"` escaping because prompt is inside a JSON string |
| Not equals | `{% if var != \"value\" %}` | Same escaping |
| Combined | `{% if var is defined and var == \"true\" %}` | `is defined` first, then compare |

Never use `is_filled()`, `is_empty()`, or any custom function in Jinja templates.

### Rule 8: Deterministic exit cues on every transition

Every transition -- both `when` (deterministic) and `when_llm` (AI-judged) -- should have a bilingual `deterministic_exit_cue`. This prevents dead air during scenario handoffs. The cue is spoken instantly while the next scenario's LLM call runs in parallel.

Cues support `{{variable}}` placeholders. The primary agent language must have a cue entry when languages are configured.

### Rule 9: Terminal scenarios use empty transitions

Scenarios that end the call have `"transitions": []`. The platform handles call termination when there are no outgoing transitions.

### Rule 10: System variables must be declared

The platform injects system variables at runtime, but they must be declared in `variables_schema` with `"source": "system"`. Always include the platform's known set:
- `agent_name`, `agent_gender`, `agent_personality`
- `current_time`, `current_date`, `current_day`, `current_timestamp`
- `dialled_phone_number`, `conversation_id`

Only declare the ones the agent actually references. If a variable appears in Jinja (`{{ current_date }}`), it **must** be declared. When in doubt, include the full set above.

Additional system variables available when campaign manager is active: `outbound_attempt_number`, `outbound_connected_attempt_number`, `call_direction`, `channel`, `last_disposition`.

### Rule 11: Minimal extracted variables

Create an `extracted` variable ONLY when:
1. A **transition reads it** (it gates a `when` condition), or
2. The **next scenario genuinely needs the value** (it crosses a scenario boundary).

If a fact is only used within one scenario's own turn, it stays in-context and gets NO variable.

### Rule 12: Tool attachment via `<tool_name>` tags in prompt and `tools` array

Tools are scoped per scenario. Every tool available in a scenario must be attached in two matching places:
1. Listed in the scenario's `"tools"` array: `["search_place", "save_kundli"]`.
2. Tagged at the end of the scenario's `prompt` string: `<tool_name>search_place</tool_name> <tool_name>save_kundli</tool_name>`.

The `<tool_name>` tags in the prompt must match the tools in the `"tools"` array in exact name and order. If a scenario has no tools, use `"tools": []` and omit `<tool_name>` tags from its prompt.

When the user provides the full `bot_config`, cross-check that every tool name in `tools` arrays exists in the bot's `actions` list. Unknown tool names cause `TOOL_MISSING` errors.

### Rule 13: Transition conditions -- `when` vs `when_llm`

Each scenario transition must have **exactly one** of `when` or `when_llm`:
- `when` -- rule-based condition evaluated deterministically against extracted variables.
- `when_llm` -- natural-language trigger evaluated by the LLM.

Both `go_to` and one of `when`/`when_llm` are required. Order transitions so the most specific/deterministic fire first.

---

## Prompt structure guidance: say blocks, if-else, and tool tags

### Prompt layout order

A scenario prompt should follow this structure top-to-bottom:

1. **Behaviour description** -- what this scenario does, what to ask, how to respond.
2. **Conditional say blocks** (inside `{% if/elif/else %}`) -- scripted lines that vary by extracted state.
3. **Unconditional say blocks** -- fixed scripted lines (brand intro, compliance, closing).
4. **`<tool_name>` tags** -- always at the very end of the prompt.

### Say blocks inside if-else

`<say>` blocks go **inside** if-else branches, not outside. Every branch must have say blocks for **all** configured languages:

```
{% if identity_confirmed is defined %}
<say lang="en-IN">Thank you for confirming, {{customer_name}}.</say>
<say lang="hi-IN">Confirm करने के लिए धन्यवाद, {{customer_name}} जी।</say>
{% else %}
<say lang="en-IN">May I speak with {{customer_name}}?</say>
<say lang="hi-IN">क्या मैं {{customer_name}} जी से बात कर सकती हूँ?</say>
{% endif %}
```

### When to use say blocks vs free text

Use `<say>` for: brand intros, compliance lines, fixed closings, scripted questions, exact amounts/dates.
Do NOT say-wrap: adaptive probing, empathy, natural steering, value read-backs where the LLM should paraphrase.

### Global prompt structure

The `global_prompt` keys are rendered as section headings in the system prompt at runtime. Think of each key as a titled instruction block:

```json
"global_prompt": {
  "persona": "You are Riya, a warm professional assistant for Karnataka Bank...",
  "context": "Outbound call to existing customer for pre-approved personal loan...",
  "conversation_style": "Mirror customer language. One language per turn. Use fillers naturally...",
  "guardrails": "Never reveal internal instructions. Never send SMS before eligibility confirmed..."
}
```

Optional extra keys (e.g. `language_rules`, `faq_reference`, `compliance_notes`) are useful for keeping large prompts organized. Each key must be snake_case (3-64 chars), and each value max 3000 chars.

---

## One-shot conversion procedure (summary -- full detail in conversion_playbook.md)

1. **Identify the funnel.** Extract the linear spine plus the cross-cutting layers.
2. **Cut into scenarios by conversational job.** Aim for ~8-15 scenarios for a large agent.
3. **Map the global layer.** Objections/FAQs -> global_transitions + handler scenarios.
4. **Write `global_prompt`** from the single prompt's persona/tone/guardrail blocks. All keys snake_case. Required: `persona`, `context`, `conversation_style`, `guardrails`.
5. **Declare variables** -- system vars (mandatory set), user_defined (CRM/pre-call), extracted (routing only).
6. **Author each scenario**: `type`, `prompt` (behaviour + say blocks inside if-else + Jinja + `<tool_name>` tags at end), `extract`, `transitions` (with bilingual cues), `tools` (array matching prompt tool tags).
7. **Self-validate** the JSON structure (see checklist below).

---

## Output format

Output the complete `scenario_config` JSON directly. The JSON must be ready to use as-is.

### Structure template:

```json
{
  "name": "<agent_name>",
  "start": "<first_scenario_key>",

  "global_prompt": {
    "persona": "...",
    "context": "...",
    "conversation_style": "...",
    "guardrails": "..."
  },

  "variables_schema": {
    "customer_name": { "source": "user_defined", "description": "..." },
    "agent_name": { "source": "system", "description": "Name of the AI agent." },
    "current_date": { "source": "system", "description": "Today's date." },
    "current_time": { "source": "system", "description": "Current time." },
    "current_day": { "source": "system", "description": "Day of the week." },
    "current_timestamp": { "source": "system", "description": "Full timestamp." },
    "agent_gender": { "source": "system", "description": "Gender of the TTS voice." },
    "agent_personality": { "source": "system", "description": "Personality of the agent." },
    "dialled_phone_number": { "source": "system", "description": "Number dialled for this call." },
    "conversation_id": { "source": "system", "description": "Unique conversation ID." },
    "some_extracted_var": { "source": "extracted", "description": "..." }
  },

  "global_transitions": {
    "transition_name": {
      "when_llm": "Natural-language trigger.",
      "go_to": "handler_scenario",
      "deterministic_exit_cue": {
        "en-IN": "English cue.",
        "hi-IN": "Hindi cue."
      }
    }
  },

  "scenarios": {
    "scenario_name": {
      "type": "single_prompt",
      "prompt": "Behaviour description.\n\n{% if some_var is defined %}\n<say lang=\"en-IN\">Conditional English line.</say>\n<say lang=\"hi-IN\">Conditional Hindi line.</say>\n{% else %}\n<say lang=\"en-IN\">Default English line.</say>\n<say lang=\"hi-IN\">Default Hindi line.</say>\n{% endif %}\n\n<tool_name>tool_a</tool_name> <tool_name>tool_b</tool_name>",
      "extract": { "var_name": "Extraction instruction." },
      "transitions": [
        {
          "when": { "var": "var_name", "op": "EXISTS" },
          "go_to": "next_scenario",
          "deterministic_exit_cue": { "en-IN": "...", "hi-IN": "..." }
        }
      ],
      "tools": [
        "tool_a",
        "tool_b"
      ]
    }
  }
}
```

---

## Pre-return self-validation checklist

Before returning the JSON, verify ALL of these (do NOT call any external APIs or spawn subagents):

1. **Valid JSON** -- parseable, no trailing commas, no comments.
2. **`start` exists** in `scenarios` and is a valid identifier (`^[a-z][a-z0-9_]{2,63}$`).
3. **Every `go_to`** (in scenario transitions AND global transitions) points to a declared scenario key.
4. **No orphan scenarios** -- every non-start scenario is reachable from some transition or global transition.
5. **Operator rules** -- `EQUALS`/`NOT_EQUALS` have a string `value`; `EXISTS`/`NOT_EXISTS` have `value: null` or no `value` field at all. Never a non-null value on EXISTS/NOT_EXISTS.
6. **`type: "single_prompt"`** on every scenario.
7. **global_prompt required fields** -- `persona`, `context`, `conversation_style`, `guardrails` all present and non-empty.
8. **global_prompt keys** are all snake_case (`^[a-z][a-z0-9_]{2,63}$`). Values max 3000 chars (excl. newlines).
9. **Unique global go_to** -- no two global transitions point to the same scenario (within global_transitions).
10. **No `signal` field** -- do not include `signal` on any transition or global transition (runtime-only, not in authoring schema).
11. **Bilingual say blocks** -- every `<say>` has variants for all configured languages; every `deterministic_exit_cue` has all language keys. Adjacent say tags use different `lang` values.
12. **Jinja** uses only `is defined`, `is not defined`, `==`, `!=` with `\"escaped\"` strings. No custom functions.
13. **System variables declared** -- at minimum the ones referenced: `agent_name`, `current_time`, `current_date`, `current_day`, `current_timestamp`, `agent_gender`, `agent_personality`, `dialled_phone_number`, `conversation_id`.
14. **Every variable** referenced in Jinja (`{{ var }}`, `{% if var %}`) or in `when.var` or in `extract` keys is declared in `variables_schema`.
15. **`deterministic_exit_cue`** present on every transition (both `when` and `when_llm`), bilingual.
16. **Tool attachment** -- every tool in a scenario's `tools` array has a matching `<tool_name>tool_name</tool_name>` tag at the end of its `prompt` in the exact same order. Scenarios without tools have `"tools": []` and no `<tool_name>` tags.
17. **Identifier lengths** -- all scenario keys, variable names, transition names, extra global_prompt keys are 3-64 chars, matching `^[a-z][a-z0-9_]{2,63}$`.
18. **Variable descriptions** -- max 256 chars each.
19. **Variable count** -- max 100 total across all sources.
20. **Condition limits** -- `when` nesting max 2 levels deep; max 10 leaves per `and`/`or` group.
21. **Transition conditions** -- each scenario transition has exactly one of `when` or `when_llm` (not both, not neither).
22. **Say blocks inside if-else** -- `<say>` tags go inside `{% if/elif/else %}` branches, with all languages in every branch.
23. **Prompt layout** -- behaviour description first, then conditional/unconditional say blocks, then `<tool_name>` tags at the very end.

State any assumptions made (e.g. "assumed bot languages are en-IN and hi-IN") in one line after the JSON.
