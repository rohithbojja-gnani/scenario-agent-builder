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

## What this does

Turns a **single giant prompt** voice agent into the **scenario-based framework**: many small reactive
scenarios the platform connects, instead of one prompt carrying all the routing. The conversion must be
**parity-or-better** — the scenario agent must respond at least as well as the single prompt.

Read this file fully, then load the reference files as needed:
- `references/schema.md` — the authoritative `scenario_config` JSON schema. **Load before writing any JSON.**
- `references/conversion_playbook.md` — step-by-step method to decompose a single prompt into scenarios.
- `references/variables.md` — canonical variable names, sources, system variables, and the "minimal extracted variables" rule.
- `references/patterns.md` — say blocks, Jinja, cues, global transitions, and anti-patterns from real migrations.

---

## The mental model

An agent = **one building block, the scenario**. A scenario is reactive: it generates output in response to
the customer's turn. The FDE authors *what a scenario says and decides*; the **platform owns** how scenarios
connect and how the call runs.

Top-level object (`scenario_config`):
- `name` (string) — identifier for the scenario config.
- `start` (string, required) — the entry scenario key.
- `global_prompt` (object) — persona / context / conversation_style / guardrails / language_rules, applied to every scenario. **Keys must be snake_case** (lowercase + underscores, 3-64 chars).
- `variables_schema` (dict) — each var has a `source`: `system` | `user_defined` | `extracted`, plus a `description`.
- `global_transitions` (dict) — cross-cutting handlers checked every turn before scenario transitions.
- `scenarios` (dict) — the scenarios; each has `type`, `prompt`, optional `tools`, `extract`, `transitions`.

---

## The rules that make a conversion correct (learned from real migrations)

### Rule 1: Operator spelling and value rules

The platform accepts these four operators in **UPPERCASE** only:

| Operator | Spelling in JSON | `value` field |
|---|---|---|
| Equals | `"EQUALS"` | Required. Always a **string** (e.g. `"true"`, `"false"`, `"accepted"`). |
| Not equals | `"NOT_EQUALS"` | Required. Always a **string**. |
| Exists | `"EXISTS"` | **Must be omitted entirely.** Validator rejects if value is present. |
| Not exists | `"NOT_EXISTS"` | **Must be omitted entirely.** Validator rejects if value is present. |

Never use `==`, `!=`, `exists`, `not exists`, `EQUALS` with no value, or `EXISTS` with a value.

### Rule 2: Every scenario needs `"type": "single_prompt"`

The frontend requires this field on every scenario object. Always include it.

### Rule 3: global_prompt keys must be snake_case

Keys like `conversationStyle` or `languageRules` will be rejected. Use `conversation_style`, `language_rules`, etc. Rule: lowercase letters, numbers, and underscores only, 3-64 characters.

### Rule 4: Unique go_to targets for global transitions

Each global transition must point to a **different** scenario. If `abuse` and `dnd_request` both need to end the call, create separate terminal scenarios for each (e.g. `abuse_closure` and `dnd_closure`).

### Rule 5: No `signal` field on global transitions

The validator rejects `signal` on `global_transitions`. Signals (`"signal": "end_call"`, `"signal": "tta"`) are only allowed on **scenario transitions** (`ScenarioTransition`).

### Rule 6: All say blocks and cues must cover all configured languages

If the bot supports `["en-IN", "hi-IN"]`, then every `<say>` block must have both `lang="en-IN"` and `lang="hi-IN"` variants, and every `deterministic_exit_cue` must have both `"en-IN"` and `"hi-IN"` keys. Mismatched languages cause validation errors.

### Rule 7: One `<say>` block per language per spoken turn

A deterministic line that runs to several sentences is **one** `<say>` block containing all of
them — never one `<say>` per sentence. A scenario renders **at most one `<say>` per configured
language** per turn; extra same-language blocks are dropped or cause a validation error.

**WRONG** — three sentences split into three same-language blocks:

```
<say lang="en-IN">Good morning.</say>
<say lang="en-IN">This is Riya from Karnataka Bank.</say>
<say lang="en-IN">Am I speaking with Mr. Sharma?</say>
<say lang="hi-IN">Good morning.</say>
<say lang="hi-IN">मैं Karnataka Bank से Riya बोल रही हूँ।</say>
<say lang="hi-IN">क्या मैं Mr. Sharma से बात कर रही हूँ?</say>
```

**RIGHT** — one block per language, all sentences inside it:

```
<say lang="en-IN">Good morning. This is Riya from Karnataka Bank. Am I speaking with Mr. Sharma?</say>
<say lang="hi-IN">Good morning. मैं Karnataka Bank से Riya बोल रही हूँ। क्या मैं Mr. Sharma से बात कर रही हूँ?</say>
```

**The one exception — Jinja branches.** Several `<say lang="en-IN">` blocks may appear in the
prompt *source* when they sit in mutually exclusive `{% if %}` / `{% elif %}` / `{% else %}`
branches, because only one branch ever renders. The rule still holds inside each branch: exactly
one `<say>` per language per branch.

If the scenario genuinely needs to speak twice with something in between — a tool call, a pause,
the customer's reply — that is **two scenarios**, not two say blocks.

Keep sentence boundaries as normal punctuation inside the single block; the TTS handles the
pauses. Do not use `\n` or separate tags to force a break.

### Rule 8: Jinja must use standard syntax only

The platform's Jinja validator does NOT have custom functions like `is_filled()`. Use only standard Jinja2:

| Check | Jinja syntax | Notes |
|---|---|---|
| Variable exists | `{% if var is defined %}` | No RHS, no escaping needed |
| Variable missing | `{% if var is not defined %}` | No RHS |
| Equals a string | `{% if var == \"value\" %}` | `\"` escaping because prompt is inside a JSON string |
| Not equals | `{% if var != \"value\" %}` | Same escaping |
| Combined | `{% if var is defined and var == \"true\" %}` | `is defined` first, then compare |

Never use `is_filled()`, `is_empty()`, or any custom function in Jinja templates.

### Rule 9: Deterministic exit cues on every transition

Every transition — both `when` (deterministic) and `when_llm` (AI-judged) — should have a bilingual `deterministic_exit_cue`. This prevents dead air during scenario handoffs. The cue is spoken instantly while the next scenario's LLM call runs in parallel.

### Rule 10: Terminal scenarios use empty transitions

Scenarios that end the call have `"transitions": []`. The platform handles call termination when there are no outgoing transitions.

### Rule 11: System variables must be declared

The platform injects system variables at runtime, but they must be declared in `variables_schema` with `"source": "system"`. Always include: `current_time`, `current_date`, `current_day`, `current_timestamp`, `agent_gender`, `agent_personality`, `dialled_phone_number`, `conversation_id`.

### Rule 12: Minimal extracted variables

Create an `extracted` variable ONLY when:
1. A **transition reads it** (it gates a `when` condition), or
2. The **next scenario genuinely needs the value** (it crosses a scenario boundary).

If a fact is only used within one scenario's own turn, it stays in-context and gets NO variable.

### Rule 13: Tool attachment via `<tool_name>` tags in prompt and `tools` array

Tools are scoped per scenario. Every tool available in a scenario must be attached in two matching places:
1. Listed in the scenario's `"tools"` array: `["search_place", "save_kundli"]`.
2. Tagged at the end of the scenario's `prompt` string: `<tool_name>search_place</tool_name> <tool_name>save_kundli</tool_name>`.

The `<tool_name>` tags in the prompt must match the tools in the `"tools"` array in exact name and order. If a scenario has no tools, use `"tools": []` and omit `<tool_name>` tags from its prompt.

---

## One-shot conversion procedure (summary — full detail in conversion_playbook.md)

1. **Identify the funnel.** Extract the linear spine plus the cross-cutting layers.
2. **Cut into scenarios by conversational job.** Aim for ~8-15 scenarios for a large agent.
3. **Map the global layer.** Objections/FAQs -> global_transitions + handler scenarios.
4. **Write `global_prompt`** from the single prompt's persona/tone/guardrail blocks. All keys snake_case.
5. **Declare variables** — system vars (mandatory set), user_defined (CRM/pre-call), extracted (routing only).
6. **Author each scenario**: `type`, `prompt` (with bilingual say blocks — **one `<say>` per language, multi-sentence lines kept inside that single block** — plus Jinja + `<tool_name>` tags at the end for attached tools), `extract`, `transitions` (with bilingual cues), `tools` (array matching prompt tool tags).
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
    "guardrails": "...",
    "language_rules": "..."
  },

  "variables_schema": {
    "customer_name": { "source": "user_defined", "description": "..." },
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
      "prompt": "Behaviour + say blocks + Jinja conditionals... <tool_name>tool_a</tool_name> <tool_name>tool_b</tool_name>",
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

Before returning the JSON, verify ALL of these (do NOT call any external APIs):

1. **Valid JSON** — parseable, no trailing commas, no comments.
2. **`start` exists** in `scenarios`.
3. **Every `go_to`** (in scenario transitions AND global transitions) points to a declared scenario key.
4. **No orphan scenarios** — every non-start scenario is reachable from some transition or global transition.
5. **Operator rules** — `EQUALS`/`NOT_EQUALS` have a string `value`; `EXISTS`/`NOT_EXISTS` have NO `value` field at all.
6. **`type: "single_prompt"`** on every scenario.
7. **global_prompt keys** are all snake_case (lowercase, underscores, 3-64 chars).
8. **Unique global go_to** — no two global transitions point to the same scenario.
9. **No `signal` on global transitions** — only on scenario transitions.
10. **Bilingual say blocks** — every `<say>` has variants for all configured languages; every `deterministic_exit_cue` has all language keys.
11. **One say block per language** — no branch of a prompt contains two `<say>` blocks with the same `lang`. Multi-sentence lines live inside a single block. (Same-language blocks in *different* Jinja branches are fine, since only one branch renders.)
12. **Jinja** uses only `is defined`, `is not defined`, `==`, `!=` with `\"escaped\"` strings. No custom functions.
13. **System variables declared** — at minimum: `current_time`, `current_date`, `current_day`, `current_timestamp`, `agent_gender`, `agent_personality`, `dialled_phone_number`, `conversation_id`.
14. **Every variable** referenced in Jinja (`{{ var }}`, `{% if var %}`) or in `when.var` or in `extract` keys is declared in `variables_schema`.
15. **`deterministic_exit_cue`** present on every transition (both `when` and `when_llm`), bilingual.
16. **Tool attachment** — every tool in a scenario's `tools` array has a matching `<tool_name>tool_name</tool_name>` tag at the end of its `prompt` in the exact same order. Scenarios without tools have `"tools": []` and no `<tool_name>` tags.

State any assumptions made (e.g. "assumed bot languages are en-IN and hi-IN") in one line after the JSON.
