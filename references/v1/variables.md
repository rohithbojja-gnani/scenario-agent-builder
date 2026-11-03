# Variables — Sources, System Variables, Minimal Extraction, Canonical Names

## The three sources

- **system** — auto-populated by the platform at call start. Must be declared in `variables_schema` with `"source": "system"`.
- **user_defined** — known before the call: CRM/contact fields and fixed values. The single prompt's `{{...}}` values map here.
- **extracted** — produced during the call by a scenario's `extract`. Carries state across scenario boundaries.

## Required system variables (always declare these)

These must be declared in every `variables_schema` to avoid `VARIABLE_MISSING` / `UNKNOWN_SYSTEM_VARIABLE` errors:

```json
"variables_schema": {
  "current_time":           { "source": "system", "description": "Current time during the turn (e.g. 12:00 PM)." },
  "current_date":           { "source": "system", "description": "Today's date (e.g. 12 July 2026)." },
  "current_day":            { "source": "system", "description": "Day of the week (e.g. Friday)." },
  "current_timestamp":      { "source": "system", "description": "Full date+time with offset." },
  "agent_gender":           { "source": "system", "description": "Gender of the TTS voice (Male/Female)." },
  "agent_personality":      { "source": "system", "description": "Personality of the agent voice." },
  "dialled_phone_number":   { "source": "system", "description": "Phone number dialled for this call." },
  "conversation_id":        { "source": "system", "description": "Unique identifier for this conversation." }
}
```

Only declare the ones the agent actually references or needs. If a variable is referenced in Jinja (`{{ current_date }}`), it MUST be declared. If not referenced anywhere, it's safe to omit. When in doubt, include the full set above.

Additional system variables available when campaign manager is active:
- `outbound_attempt_number`, `outbound_connected_attempt_number`, `call_direction`, `channel`, `last_disposition`.

## Rule: MINIMAL extracted variables

Create an `extracted` variable **only if** at least one of:
1. A **transition reads it** (it gates a `when` condition), or
2. The **next scenario genuinely needs the value** (crosses a scenario boundary).

If a fact is only used within one scenario's own turn — tone, which rebuttal was used, soft acknowledgements — it stays in-context and gets NO variable.

### Naming extracted routing flags
- Prefer null-until-set flags tested with `EXISTS`: e.g. `identity_confirmed` tested with `{"var": "identity_confirmed", "op": "EXISTS"}`.
- Use `EQUALS`/`NOT_EQUALS` only for genuine enums: e.g. `{"var": "is_employed", "op": "EQUALS", "value": "true"}`.
- Extraction values are always **strings**: `"true"`, `"false"`, `"accepted"`, `"declined"`, `"not_eligible"`.

### Typical good extracted sets (by agent type):

**Identity/greeting:** `identity_confirmed`, `is_third_party`
**Eligibility routing:** `is_employed`, `has_epf`, `has_official_email`
**Payment/booking:** `payment_date`, `payment_mode`, `payment_confirmed`
**Consent:** `sms_consent`, `callback_time`
**Control:** `rebuttal_done`, `rebuttal_outcome`, `call_outcome`, `wants_to_end`

Target: 10-20 extracted variables for a large agent. If past ~25, you're over-extracting.

## Canonical names (enforce; collapse language variants)

| Concept | Canonical | Never use |
|---|---|---|
| Today's date | `current_date` | today_date, todays_date, date_today |
| Customer name | `customer_name` or `full_name` | name, customer_full_name |
| Phone | `phone_number` | mobile, mob, rmn |
| Loan account | `loan_id` | loan_account_number |
| Amount fields | `due_amount`, `total_loan_amount` | due_amount_eng/hin |
| Agent name | `agent_name` | bot_name, assistant_name |

Collapse every `_eng` / `_hin` / `_tam` variant to the single base name. Language is handled at speak time, not via separate variables.

## Variable definition shape in output

```json
"variables_schema": {
  "customer_name":        { "source": "user_defined", "description": "Full name of the customer." },
  "agent_name":           { "source": "user_defined", "description": "Name of the AI agent." },
  "current_date":         { "source": "system",       "description": "Today's date." },
  "current_time":         { "source": "system",       "description": "Current time." },
  "current_day":          { "source": "system",       "description": "Day of the week." },
  "current_timestamp":    { "source": "system",       "description": "Full timestamp." },
  "agent_gender":         { "source": "system",       "description": "Gender of the TTS voice." },
  "agent_personality":    { "source": "system",       "description": "Personality of the agent." },
  "dialled_phone_number": { "source": "system",       "description": "Number dialled for this call." },
  "conversation_id":      { "source": "system",       "description": "Unique conversation ID." },
  "is_employed":          { "source": "extracted",    "description": "Whether customer is employed. 'true' or 'false'." },
  "callback_time":        { "source": "extracted",    "description": "When the customer wants to be called back." }
}
```

## Domain suggestion packs (offer when authoring)

### Universal core (every agent)
- **Customer Info (user_defined):** `customer_name`, `first_name`, `phone_number`, `customer_type`, `gender`, `city`, `preferred_language`, `agent_name`, `callback_time`.
- **System:** the required system set above.

### Collections / lending pack (user_defined)
`loan_id`, `loan_type`, `total_loan_amount`, `tenure`, `no_of_loans`, `bank_name`, `nach_status`, `last_4_digits`, `due_date`, `due_amount`, `emi_amount`, `due_days`, `due_month`, `total_overdue`, `total_due_amount`, `dpd`, `penalty_amount`, `bounce_charges`, `min_partial_amount`, `settlement_amount`, `last_payment_amount`, `last_payment_date`, `mode_of_payment`, `salary_date`, `commit_date`.

### Insurance pack (user_defined)
`current_insurer`, `current_plan_name`, `sum_insured`, `annual_premium`, `renewal_date`, `policy_number`, `policy_type`, `family_members_covered`.
