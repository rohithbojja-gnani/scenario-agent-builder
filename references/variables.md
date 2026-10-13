# Variables (version 2): sources, types, minimal extraction, canonical names

## Sources

| Source | Who sets it | Type | Updated by the model |
|---|---|---|---|
| `system` | The platform, at call start | `text` | Never (`SYSTEM_VARIABLE_UPDATE`) |
| `user_defined` | Supplied with each call (campaign/CRM data, fixed values) | `text` | Allowed, for corrections |
| `extracted` | Captured from the conversation via `<update>` or a waiting If | `text`, `number`, `decimal`, `boolean`, `enum` | Yes |

## System variables

Exactly these nine exist; declare the ones you use (type `text`):

```json
"agent_name":           {"source": "system", "type": "text", "description": "Name of the AI agent."},
"agent_gender":         {"source": "system", "type": "text", "description": "Gender of the agent voice (Male or Female)."},
"agent_personality":    {"source": "system", "type": "text", "description": "Personality of the voice persona."},
"current_date":         {"source": "system", "type": "text", "description": "Today's date at call start."},
"current_day":          {"source": "system", "type": "text", "description": "Day of the week at call start."},
"current_time":         {"source": "system", "type": "text", "description": "Time at call start."},
"current_timestamp":    {"source": "system", "type": "text", "description": "Full timestamp at call start, for date maths."},
"dialled_phone_number": {"source": "system", "type": "text", "description": "Phone number dialled for this call."},
"conversation_id":      {"source": "system", "type": "text", "description": "Unique conversation ID."}
```

Anything else that arrives with the call (amounts, names, dates, account data, a "today" field from the campaign)
is `user_defined`. Don't declare a second "today" variable: use `current_date`.

## Choosing a type for an extracted variable

| Value | Type | Notes |
|---|---|---|
| Yes/no fact or "line already said" flag | `boolean` | Conditions use `EQUALS true/false` only. `yes`/`no` are not accepted values |
| One of 2 to 10 categories | `enum` | Options: letters, digits, space, `_`, `-`; ≤ 64 characters; not number- or boolean-looking (`tier1`, not `1`) |
| A code with more than 10 possible values (e.g. call dispositions) | `text` | List the codes in a global prompt section and say "exactly one of the codes" in the description |
| Dates, times, names, free amounts as spoken | `text` | State the format: `YYYY-MM-DD`, `YYYY-MM-DD HH:MM` |
| Whole numbers compared with GREATER/LESS | `number` | EQUALS needs a whole number |
| Amounts with decimals compared in conditions | `decimal` | |

## Descriptions

The description is shown every time the model is asked to report the variable. Make it say what the value is,
in one sentence, ≤ 256 characters. Put per-scenario guidance (when to report it here) in the scenario text next to
the `<update>`, not in the description.

## Minimal extraction

Create an `extracted` variable only if:
1. a condition reads it (it routes the call), or
2. another scenario needs the value, or
3. it is a required output of the call (disposition, committed date/amount/mode, callback time).

A fact used only within one scenario's own turn stays in the conversation. Target 10–25 extracted variables for a
large agent; well over that usually means "line already said" bookkeeping that the history or the flow already
covers.

## Reporting rules worth stating in scenarios

- "Report it on the turn it becomes true; never report a value you don't have."
- For flags about lines said in the first reply after a move: "report it on the customer's next turn, including
  when it was said as this scenario started".
- Stable identifiers: update them only where they can change (not in every scenario).

## Canonical names

| Concept | Name | Never |
|---|---|---|
| Today's date | `current_date` | today_date, todays_date, date_today |
| Customer name | `customer_name` or `full_name` | name, customer_full_name |
| Phone | `phone_number` | mobile, mob, rmn |
| Loan account | `loan_id` | loan_account_number |
| Amounts | `due_amount`, `total_loan_amount` | due_amount_eng / due_amount_hin |
| Agent name | `agent_name` | bot_name, assistant_name |

Collapse every `_eng` / `_hin` language variant into one base name unless the campaign really supplies separate
spoken forms (then keep `x_english` and `x_translated` and say which one each language uses).

## Domain packs (user_defined, all `text`)

- **Core**: `customer_name`, `first_name`, `phone_number`, `customer_type`, `gender`, `city`, `preferred_language`,
  `callback_time`.
- **Collections / lending**: `loan_id`, `loan_type`, `total_loan_amount`, `tenure`, `bank_name`, `due_date`,
  `due_amount`, `emi_amount`, `dpd`, `total_overdue`, `settlement_amount`, `last_payment_amount`, `last_payment_date`.
- **Insurance**: `policy_number`, `policy_type`, `current_insurer`, `sum_insured`, `annual_premium`, `renewal_date`.
