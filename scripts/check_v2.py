#!/usr/bin/env python3
"""Offline check of a scenario_config version 2 before it is saved.

Mirrors the save-time validator of genvoice_backend_v1 (main/scenario_v2/*), plus:
- the contract's transition type/mode rules the editor enforces;
- FE_* : rules/bugs of the Inya editor (genvoice_app_frontend) that block Validate/Save or lose data;
- LINT_* : runtime behaviour of genvoice_backend v2 that hurts calls or latency (warnings).
Standard library only.

usage:
  python3 scripts/check_v2.py CONFIG.json --languages en-IN,hi-IN [--tools a,b] [--greeting TEXT] [--ending TEXT]

CONFIG.json may be the scenario_config itself, or a bot_config holding it under "scenario_config".
--languages: the bot's languages, primary first. --tools: the bot's action names (omit to skip TOOL_MISSING).
Exit code 1 when there are errors. Warnings never fail.
"""
import argparse
import json
import re
import sys
import unicodedata
from xml.parsers import expat

NAME_RE = re.compile(
    r"^[a-z぀-ゟ゠-ヿ一-鿿][a-z0-9_぀-ゟ゠-ヿ一-鿿]{2,63}$"
)
TOP_KEYS = {"version", "start", "global_prompt", "variables_schema", "global_transitions", "scenarios"}
SOURCES = {"system", "user_defined", "extracted"}
TYPES = {"text", "number", "decimal", "boolean", "enum"}
REQUIRED_SECTIONS = ("persona", "context", "conversation_style", "guardrails")
TAGS = {"update", "tool", "say", "transition", "filler", "text", "male", "female", "if", "elif", "else"}
LIMITS = dict(scenarios=100, global_transitions=50, variables=100, description=256, section=3000,
              when_llm=1000, scenario_text=5000, line=1000, if_depth=3, conditions=10, brackets=3,
              enum_min=2, enum_max=10, enum_len=64)
LINK_RE = re.compile(r"(?:\b(?:https?|ftp)://|\bwww\.)", re.I)
MUSTACHE_RE = re.compile(r"\{\{(.*?)\}\}", re.S)
TAG_LIKE_RE = re.compile(r"<\s*/?\s*[A-Za-z][^<>]*>")
UNDERLINE_PAIR_RE = re.compile(r"<u>((?:(?!</?u>).)*)</u>", re.S)
NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
OPS_BY_TYPE = {
    "text": {"EQUALS", "NOT_EQUALS"},
    "number": {"EQUALS", "NOT_EQUALS", "GREATER_THAN", "GREATER_OR_EQUAL", "LESS_THAN", "LESS_OR_EQUAL"},
    "boolean": {"EQUALS"},
    "enum": {"EQUALS", "NOT_EQUALS", "IN", "NOT_IN"},
}
OPS_BY_TYPE["decimal"] = OPS_BY_TYPE["number"]
OPERATORS = set().union(*OPS_BY_TYPE.values()) | {"EXISTS", "NOT_EXISTS"}
FE_ENUM_RE = re.compile(r"^[a-zA-Z0-9 _-]+$")
GENDER_TAGS = ("male", "female")


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, code, msg, path="", line=None):
        self.errors.append((code, path, line, msg))

    def warn(self, code, msg, path="", line=None):
        self.warnings.append((code, path, line, msg))


# ---------------------------------------------------------------- XML ---------
class Node:
    def __init__(self, tag, attrs, line, path):
        self.tag, self.attrs, self.line, self.path, self.children = tag, attrs, line, path, []

    @property
    def elements(self):
        return [c for c in self.children if isinstance(c, Node)]

    def texts(self):  # [(text, line)] directly inside
        return [c for c in self.children if isinstance(c, tuple)]

    def words(self):
        return "".join(t for t, _ in self.texts()).strip()


def parse_fragment(text, root_tag, base_path, rep):
    """Parse ``text`` wrapped in <root_tag>. Returns the root Node or None."""
    root, stack, counters, underline = None, [], [], [0]
    p = expat.ParserCreate()
    p.buffer_text = True

    def start(name, attrs):
        nonlocal root
        if name == "u" and stack:  # editor underline: no node, words stay in the run
            underline[0] += 1
            return
        line = p.CurrentLineNumber
        if not stack:
            root = Node(name, attrs, line, base_path)
            stack.append(root)
            counters.append({})
            return
        parent = stack[-1]
        counters[-1][name] = counters[-1].get(name, 0) + 1
        node = Node(name, attrs, line, f"{parent.path}/{name}[{counters[-1][name]}]")
        parent.children.append(node)
        stack.append(node)
        counters.append({})

    def end(name):
        if name == "u" and underline[0]:
            underline[0] -= 1
            return
        stack.pop()
        counters.pop()

    def chars(data):
        if stack:
            stack[-1].children.append((data, p.CurrentLineNumber))

    def comment(_data):
        rep.error("COMMENT_NOT_ALLOWED", "XML comments are not allowed.", base_path, p.CurrentLineNumber)

    def pi(_target, _data):
        rep.error("COMMENT_NOT_ALLOWED", "Processing instructions are not allowed.", base_path, p.CurrentLineNumber)

    def doctype(*_a):
        rep.error("XML_MALFORMED", "A DOCTYPE is not allowed.", base_path, p.CurrentLineNumber)

    p.StartElementHandler, p.EndElementHandler, p.CharacterDataHandler = start, end, chars
    p.CommentHandler, p.ProcessingInstructionHandler, p.StartDoctypeDeclHandler = comment, pi, doctype
    try:
        p.Parse(f"<{root_tag}>{text}</{root_tag}>", True)
    except expat.ExpatError as exc:
        rep.error("XML_MALFORMED", f"Not well-formed XML ({expat.errors.messages.get(exc.code, exc)}). "
                  "Write & as &amp; and < as &lt; in text.", base_path, exc.lineno)
        return None
    return root


# ---------------------------------------------------------------- when --------
class WhenError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def tokenize(text):
    toks, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "(),":
            toks.append((ch, ch))
            i += 1
        elif ch == "'":
            i, buf = i + 1, []
            while True:
                if i >= n:
                    raise WhenError("WHEN_SYNTAX", "A quoted string is missing its closing quote.")
                if text[i] == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(text[i])
                i += 1
            toks.append(("str", "".join(buf)))
        else:
            s = i
            while i < n and not text[i].isspace() and text[i] not in "(),'":
                i += 1
            toks.append(("word", text[s:i]))
    return toks


def parse_when(text):
    """Returns [(var, op, kind, value)]; raises WhenError."""
    if not text.strip():
        raise WhenError("WHEN_SYNTAX", "The condition is empty.")
    toks, pos, conds, mixed = tokenize(text), [0], [], [False]
    peek = lambda: toks[pos[0]] if pos[0] < len(toks) else None  # noqa: E731

    def condition():
        t = peek()
        if not t or t[0] != "word" or t[1] in OPERATORS:
            raise WhenError("WHEN_SYNTAX", "Expected a variable name at the start of a condition.")
        name = t[1]
        pos[0] += 1
        t = peek()
        if not t or t[0] != "word" or t[1] not in OPERATORS:
            raise WhenError("WHEN_SYNTAX", f"Expected an operator after '{name}' (EQUALS, GREATER_THAN, IN, EXISTS, ...).")
        op = t[1]
        pos[0] += 1
        kind = value = None
        if op not in ("EXISTS", "NOT_EXISTS"):
            t = peek()
            if t is None:
                raise WhenError("WHEN_SYNTAX", f"Expected a value after {op}.")
            if t[0] == "str":
                kind, value = "string", t[1]
            elif t[0] == "word" and t[1] in ("true", "false"):
                kind, value = "boolean", t[1] == "true"
            elif t[0] == "word" and NUMBER_RE.match(t[1]):
                kind, value = "number", float(t[1])
            elif t[0] == "(":
                pos[0] += 1
                items = []
                while True:
                    it = peek()
                    if not it or it[0] != "str":
                        raise WhenError("WHEN_SYNTAX", "A list holds quoted strings, for example ('a', 'b').")
                    items.append(it[1])
                    pos[0] += 1
                    sep = peek()
                    if sep and sep[0] == ",":
                        pos[0] += 1
                        continue
                    if sep and sep[0] == ")":
                        break
                    raise WhenError("WHEN_SYNTAX", "A list holds quoted strings, for example ('a', 'b').")
                kind, value = "list", items
            else:
                raise WhenError("WHEN_SYNTAX", f"'{t[1]}' is not a valid value: quote strings, leave numbers and true/false bare.")
            pos[0] += 1
        conds.append((name, op, kind, value))
        return op

    def level(depth):
        joiners = []
        while True:
            last = None
            t = peek()
            if t and t[0] == "(":
                if depth >= LIMITS["brackets"]:
                    raise WhenError("WHEN_SYNTAX", f"Brackets nested deeper than {LIMITS['brackets']} levels.")
                pos[0] += 1
                level(depth + 1)
                t = peek()
                if not t or t[0] != ")":
                    raise WhenError("WHEN_SYNTAX", "A group is missing its closing ')'.")
                pos[0] += 1
            else:
                last = condition()
            t = peek()
            if t and t[0] == "word" and t[1] in ("AND", "OR"):
                joiners.append(t[1])
                pos[0] += 1
                continue
            if t is None or t[0] == ")":
                break
            raise WhenError("WHEN_SYNTAX", f"{last} takes no value." if last in ("EXISTS", "NOT_EXISTS")
                            else f"Unexpected '{t[1]}'. Join conditions with AND or OR.")
        if len(set(joiners)) > 1:
            mixed[0] = True

    level(0)
    if pos[0] < len(toks):
        raise WhenError("WHEN_SYNTAX", "A ')' has no matching '('.")
    if mixed[0]:
        raise WhenError("WHEN_MIXED_JOINERS", "Use AND or OR at one level, not both: bracket one side, e.g. (a AND b) OR c.")
    return conds


def fe_bracket_problem(text):
    """The editor parses brackets one level deep, and only when every top-level part is bracketed."""
    depth = deepest = 0
    parts, expect, in_list, prev = [], True, False, None
    for kind, val in tokenize(text):
        if in_list:
            in_list = kind != ")"
        elif kind == "(":
            if prev and prev[1] in ("IN", "NOT_IN"):
                in_list = True
            else:
                if depth == 0 and expect:
                    parts.append(True)
                depth += 1
                deepest = max(deepest, depth)
            expect = False
        elif kind == ")":
            depth -= 1
        elif kind == "word" and val in ("AND", "OR") and depth == 0:
            expect = True
        else:
            if depth == 0 and expect:
                parts.append(False)
            expect = False
        prev = (kind, val)
    if deepest > 1:
        return "the editor can't parse nested brackets; flatten to one level"
    if any(parts) and not all(parts):
        return "the editor needs every top-level part bracketed: write (a OR b) AND (c), not (a OR b) AND c"
    return None


def check_condition(var, op, kind, value, d):
    """None when fine, else a CONDITION_TYPE_MISMATCH message."""
    if op in ("EXISTS", "NOT_EXISTS"):
        return None
    t = d.get("type")
    if op not in OPS_BY_TYPE.get(t, ()):
        return f"{op} is not supported for {t} variables (text: EQUALS/NOT_EQUALS; boolean: EQUALS only)."
    if t == "text":
        return None if kind == "string" else f"{var} is text: quote the value."
    if t == "boolean":
        return None if kind == "boolean" else f"{var} is boolean: write true or false without quotes."
    if t in ("number", "decimal"):
        if kind != "number":
            return f"{var} is a {t}: the value must be a bare number."
        if t == "number" and op in ("EQUALS", "NOT_EQUALS") and value != int(value):
            return f"{op} on {var} needs a whole number."
        return None
    allowed = {v.strip().casefold() for v in d.get("allowed_values") or []}
    if op in ("IN", "NOT_IN"):
        if kind != "list":
            return f"{op} takes a list such as ('a', 'b')."
        bad = [v for v in value if v.strip().casefold() not in allowed]
        return f"{bad} not in allowed_values of {var}." if bad else None
    if kind != "string" or value.strip().casefold() not in allowed:
        return f"{value!r} is not one of the allowed_values of {var}."
    return None


# ---------------------------------------------------------------- checker -----
def enum_problem(values):
    if not isinstance(values, list):
        return "Add at least 2 unique options."
    cleaned = []
    for v in values:
        if not isinstance(v, str) or not v.strip():
            return "Options cannot be empty."
        cleaned.append(v.strip())
    if len({v.casefold() for v in cleaned}) != len(cleaned):
        return "Options must be unique (ignoring case)."
    if not LIMITS["enum_min"] <= len(cleaned) <= LIMITS["enum_max"]:
        return f"A list needs {LIMITS['enum_min']}-{LIMITS['enum_max']} options."
    for v in cleaned:
        if v == "<DEFAULT>":
            return "<DEFAULT> is not an allowed option."
        if len(v) > LIMITS["enum_len"]:
            return f"Option '{v[:20]}...' is longer than {LIMITS['enum_len']} characters."
        if not all(c in " _-" or unicodedata.category(c)[0] in "LMN" for c in v):
            return f"Option '{v}' can only contain letters, numbers, spaces, hyphens and underscores."
    return None


class Checker:
    def __init__(self, cfg, langs, tools, rep):
        self.cfg, self.langs, self.tools, self.rep = cfg, langs, tools, rep
        self.vars = cfg.get("variables_schema") or {}
        self.scenarios = cfg.get("scenarios") or {}
        self.targets, self.asked = set(), set()
        self.transition_whens, self.say_only = [], set()
        self.counts = {"transitions": 0, "llm_exits": 0, "waits": 0}

    # -- schema ---------------------------------------------------------------
    def schema(self):
        c, e = self.cfg, self.rep.error
        bad = lambda m, p="": e("SCHEMA_INVALID", m, p)  # noqa: E731
        for k in set(c) - TOP_KEYS:
            bad(f"'{k}' is not a supported field (no 'name', 'signal', 'type' on the config).", k)
        if c.get("version") != 2 or isinstance(c.get("version"), bool):
            bad("version must be the number 2.", "version")
        if not isinstance(c.get("start"), str) or not NAME_RE.match(c.get("start", "")):
            bad("start must be a valid scenario name.", "start")
        sc = c.get("scenarios")
        if not isinstance(sc, dict) or not sc:
            bad("scenarios must be an object with at least one scenario.", "scenarios")
        else:
            if len(sc) > LIMITS["scenarios"]:
                bad(f"At most {LIMITS['scenarios']} scenarios.", "scenarios")
            for name, body in sc.items():
                if not NAME_RE.match(name):
                    bad(f"Invalid scenario name {name}.", f"scenarios.{name}")
                if not isinstance(body, str) or not body:
                    bad("A scenario is one non-empty string (not an object).", f"scenarios.{name}")
        gp = c.get("global_prompt")
        if not isinstance(gp, dict):
            bad("global_prompt is required.", "global_prompt")
        else:
            for key in REQUIRED_SECTIONS:
                val = gp.get(key, gp.get("conversationStyle") if key == "conversation_style" else None)
                if not isinstance(val, str) or not val:
                    bad(f"global_prompt.{key} is required and non-empty.", f"global_prompt.{key}")
            for key, val in gp.items():
                if key not in REQUIRED_SECTIONS and key != "conversationStyle" and not NAME_RE.match(key):
                    bad(f"Invalid global_prompt key {key}.", f"global_prompt.{key}")
                if not isinstance(val, str):
                    bad("global_prompt values are strings.", f"global_prompt.{key}")
                elif len(val.replace("\n", "").replace("\r", "")) > LIMITS["section"]:
                    bad(f"Over {LIMITS['section']} characters (newlines not counted).", f"global_prompt.{key}")
        vs = c.get("variables_schema", {})
        if not isinstance(vs, dict):
            bad("variables_schema must be an object.", "variables_schema")
            self.vars = {}
        else:
            if len(vs) > LIMITS["variables"]:
                bad(f"At most {LIMITS['variables']} variables (system ones count).", "variables_schema")
            for name, d in vs.items():
                p = f"variables_schema.{name}"
                if not NAME_RE.match(name):
                    bad(f"Invalid variable name {name}.", p)
                if not isinstance(d, dict):
                    bad("A variable is an object.", p)
                    continue
                for k in set(d) - {"source", "type", "description", "allowed_values"}:
                    bad(f"'{k}' is not a supported field.", p)
                if d.get("source") not in SOURCES:
                    bad("source must be system, user_defined or extracted.", p)
                if d.get("type") not in TYPES:
                    bad("type must be text, number, decimal, boolean or enum.", p)
                if not isinstance(d.get("description", ""), str) or len(d.get("description", "")) > LIMITS["description"]:
                    bad(f"description is a string of at most {LIMITS['description']} characters.", p)
                if d.get("type") == "enum" and d.get("allowed_values") is None:
                    bad("allowed_values is required when type is enum.", p)
                if d.get("type") != "enum" and "allowed_values" in d:
                    bad("allowed_values is only allowed when type is enum.", p)
                if d.get("source") in ("system", "user_defined") and d.get("type") != "text":
                    bad(f"{d.get('source')} variables must have type text.", p)
        gts = c.get("global_transitions", {})
        if not isinstance(gts, dict):
            bad("global_transitions must be an object.", "global_transitions")
        else:
            if len(gts) > LIMITS["global_transitions"]:
                bad(f"At most {LIMITS['global_transitions']} global transitions.", "global_transitions")
            for name, gt in gts.items():
                p = f"global_transitions.{name}"
                if not NAME_RE.match(name):
                    bad(f"Invalid global transition name {name}.", p)
                if not isinstance(gt, dict):
                    bad("A global transition is an object.", p)
                    continue
                for k in set(gt) - {"when_llm", "go_to", "filler"}:
                    bad(f"'{k}' is not a supported field (v1 deterministic_exit_cue -> filler).", p)
                w = gt.get("when_llm")
                if not isinstance(w, str) or not w or len(w) > LIMITS["when_llm"]:
                    bad(f"when_llm is required, 1-{LIMITS['when_llm']} characters.", p)
                if not isinstance(gt.get("go_to"), str) or not NAME_RE.match(gt.get("go_to") or ""):
                    bad("go_to must be a valid scenario name.", p)
                if "filler" in gt and (not isinstance(gt["filler"], str) or not gt["filler"]):
                    bad("filler is a non-empty string of <text> elements.", p)
        return not self.rep.errors

    # -- plain text and templates ---------------------------------------------
    def templates(self, text, path, line=None):
        for tok in ("{%", "{#"):
            if tok in text:
                self.rep.error("TEMPLATE_NOT_ALLOWED", f"{tok} is not allowed: only {{{{name}}}}; use <if when> for logic.", path, line)
        spans = []
        for m in MUSTACHE_RE.finditer(text):
            spans.append(m.span())
            inner = m.group(1)
            if not re.fullmatch(r"\w+", inner):
                self.rep.error("TEMPLATE_NOT_ALLOWED", "Only plain {{name}}: no spaces, filters or expressions.", path, line)
            elif inner not in self.vars:
                self.rep.error("VARIABLE_MISSING", f"The variable '{inner}' does not exist.", path, line)
        for m in re.finditer(r"\{\{", text):
            if not any(s <= m.start() < e for s, e in spans):
                self.rep.error("TEMPLATE_NOT_ALLOWED", "A {{ is missing its closing }}.", path, line)

    def links(self, text, path, line=None):
        if LINK_RE.search(text):
            self.rep.error("LINK_NOT_ALLOWED", "Links are not allowed. Remove the web address.", path, line)

    def plain(self, text, path):
        rest = UNDERLINE_PAIR_RE.sub(r"\1", text)
        if re.search(r"</?u>", rest) or TAG_LIKE_RE.search(rest):
            self.rep.error("MARKUP_IN_GLOBAL_PROMPT", "No tags here (not even <Heading>-style): plain text only.", path)
        self.templates(text, path)

    # -- spoken lines -----------------------------------------------------------
    def lines(self, box):
        texts, seen = [], {}
        for ch in box.children:
            if isinstance(ch, tuple):
                if ch[0].strip():
                    self.rep.error("MISPLACED_ELEMENT", 'Spoken words must be inside <text lang="...">.', box.path, ch[1])
            elif ch.tag == "text":
                texts.append(ch)
            else:
                self.stray(ch, f"<{ch.tag}> can't be used inside <{box.tag}>.")
        for t in texts:
            self.text_el(t, allow_vars=box.tag == "say")
            lang = (t.attrs.get("lang") or "").strip()
            if not lang:
                continue
            if lang in seen:
                self.rep.error("DUPLICATE_LANGUAGE", f"Two {lang} texts in one <{box.tag}>.", t.path, t.line)
            seen.setdefault(lang, t)
            if self.langs and lang not in self.langs:
                self.rep.warn("LANGUAGE_NOT_CONFIGURED", f"{lang} is not one of the bot's languages.", t.path, t.line)
        if self.langs and texts and self.langs[0] in seen and (texts[0].attrs.get("lang") or "").strip() != self.langs[0]:
            self.rep.warn("PRIMARY_NOT_FIRST", f'Put <text lang="{self.langs[0]}"> first: the editor keeps the first line of a filler.', box.path, box.line)
        if self.langs and self.langs[0] not in seen:
            self.rep.error("PRIMARY_LANGUAGE_MISSING", f'Every <{box.tag}> needs <text lang="{self.langs[0]}">.', box.path, box.line)
        missing = [lang for lang in self.langs[1:] if lang not in seen]
        if missing:
            self.rep.warn("LINT_LANGUAGE_MISSING", f"No {', '.join(missing)} line: callers in that language hear the primary-language line.", box.path, box.line)
        paired = [any(e.tag in GENDER_TAGS for e in t.elements) for t in texts]
        if any(paired) and not all(paired):
            self.rep.error("FE_MIXED_VOICES", "Some <text> have <male>/<female> and some don't: the editor drops the plain ones on re-save. Pair every language.", box.path, box.line)
        elif texts and not any(paired):
            self.rep.warn("FE_NO_VOICE_PAIRS", "No <male>/<female> lines: the editor flags it as untranslated. Pair every language (identical text is fine).", box.path, box.line)
        for t in texts:
            for line in [t] + [e for e in t.elements if e.tag in GENDER_TAGS]:
                if "Note:" in line.words():
                    self.rep.warn("LINT_STOP_WORD", "'Note:' is the model's stop sequence: a model-spoken line is cut there.", t.path, t.line)

    def text_el(self, t, allow_vars):
        self.attrs(t, required=("lang",))
        voices = [e for e in t.elements if e.tag in ("male", "female")]
        for other in t.elements:
            if other.tag not in ("male", "female"):
                self.stray(other, f"<{other.tag}> can't be used inside <text>.")
        if voices:
            males = [v for v in voices if v.tag == "male"]
            if len(males) != 1 or len(voices) != 2 or t.words():
                self.rep.error("VOICE_PAIR_INCOMPLETE", "A <text> holds plain words, or exactly one <male> and one <female>.", t.path, t.line)
            for v in voices:
                self.attrs(v)
                for x in v.elements:
                    self.stray(x, f"<{x.tag}> can't be used inside <{v.tag}>.")
                self.spoken(v, allow_vars)
            return
        self.spoken(t, allow_vars)

    def spoken(self, node, allow_vars):
        words = node.words()
        if not words:
            self.rep.error("EMPTY_LINE", f"<{node.tag}> has no words.", node.path, node.line)
        if len(words) > LIMITS["line"]:
            self.rep.error("TEXT_TOO_LONG", f"Spoken line is {len(words)} characters (limit {LIMITS['line']}).", node.path, node.line)
        for text, line in node.texts():
            self.links(text, node.path, line)
            if allow_vars:
                self.templates(text, node.path, line)
            elif "{{" in text:
                self.rep.error("VARIABLE_IN_SPOKEN_LINE", "Filler lines are plain text: no {{...}}.", node.path, line)

    # -- scenario bodies --------------------------------------------------------
    def stray(self, node, msg):
        if node.tag in TAGS:
            self.rep.error("MISPLACED_ELEMENT", msg, node.path, node.line)
        else:
            self.rep.error("UNKNOWN_ELEMENT", f"<{node.tag}> is not a supported tag.", node.path, node.line)

    def attrs(self, node, required=(), optional=()):
        for a in node.attrs:
            if a not in required and a not in optional:
                self.rep.error("UNKNOWN_ATTRIBUTE", f"<{node.tag}> has no attribute '{a}'.", node.path, node.line)
        for a in required:
            if not (node.attrs.get(a) or "").strip():
                self.rep.error("MISSING_ATTRIBUTE", f"<{node.tag}> needs {a}.", node.path, node.line)

    def scenario(self, name, text):
        root = parse_fragment(text, "scenario", f"scenarios.{name}", self.rep)
        if root is None:
            return
        size = self.text_len(root)
        if size > LIMITS["scenario_text"]:
            self.rep.error("TEXT_TOO_LONG", f"Scenario text is {size} characters (limit {LIMITS['scenario_text']}; "
                           "instructions + every <say> line in every language/voice, fillers and tags excluded).",
                           f"scenarios.{name}")
        before = dict(self.counts)
        self.body(root, name, 0)
        delta = {k: self.counts[k] - before[k] for k in self.counts}
        if name in self.say_only and not delta["transitions"]:
            self.rep.warn("LINT_SAY_ONLY", "Only <say> lines and no transition: spoken without the model, so it never "
                          "ends the call (no EOC), catches no interrupt, and repeats on the next turn. Add an instruction line.",
                          f"scenarios.{name}")
        if delta["waits"] and not delta["llm_exits"]:
            self.rep.warn("LINT_NO_ESCAPE", "Conditions wait on extracted variables but there is no mode=\"llm\" exit: "
                          "a caller who won't answer is asked forever.", f"scenarios.{name}")
        if size > 2500:
            self.rep.warn("LINT_SCENARIO_LONG", f"{size} chars of scenario text are re-sent uncached every turn: move static "
                          "content to global_prompt or split the scenario.", f"scenarios.{name}")

    def text_len(self, node):
        total = 0
        for ch in node.children:
            if isinstance(ch, tuple):
                total += len(ch[0].strip())
            elif ch.tag != "filler":
                total += self.text_len(ch)
        return total

    def body(self, node, scenario, depth):
        chain = None
        for ch in node.children:
            if isinstance(ch, tuple):
                self.links(ch[0], node.path, ch[1])
                self.templates(ch[0], node.path, ch[1])
                if ch[0].strip():
                    chain = None
                continue
            tag = ch.tag
            if tag in ("if", "elif"):
                if tag == "elif" and chain not in ("if", "elif"):
                    self.rep.error("MISPLACED_ELEMENT", "<elif> must directly follow </if> or </elif>.", ch.path, ch.line)
                self.branch(ch, scenario, depth, is_elif=tag == "elif")
                chain = tag
            elif tag == "else":
                if chain not in ("if", "elif"):
                    self.rep.error("MISPLACED_ELEMENT", "<else> must directly follow </if> or </elif>.", ch.path, ch.line)
                self.attrs(ch)
                if depth + 1 <= LIMITS["if_depth"]:
                    self.branch_body(ch, scenario, depth + 1)
                chain = "else"
            else:
                chain = None
                if tag == "update":
                    self.update(ch)
                elif tag == "tool":
                    self.tool(ch)
                elif tag == "say":
                    self.attrs(ch)
                    self.lines(ch)
                elif tag == "transition":
                    self.transition(ch, scenario, depth, node)
                else:
                    self.stray(ch, f"<{tag}> can't be used here.")

    def branch(self, node, scenario, depth, is_elif):
        self.attrs(node, required=("when",))
        if depth + 1 > LIMITS["if_depth"]:
            if not is_elif:
                self.rep.error("IF_NESTING", f"<if> nested deeper than {LIMITS['if_depth']} levels.", node.path, node.line)
            return
        if (node.attrs.get("when") or "").strip():
            self.when(node, node.attrs["when"])
        self.branch_body(node, scenario, depth + 1)

    def branch_body(self, node, scenario, depth):
        if not node.elements and not node.words():
            self.rep.warn("EMPTY_BRANCH", f"<{node.tag}> is empty.", node.path, node.line)
            self.rep.error("FE_EMPTY_BRANCH", "The editor blocks empty <if>/<elif>/<else> bodies.", node.path, node.line)
        self.body(node, scenario, depth)

    def update(self, node):
        self.attrs(node, required=("var",))
        if node.elements or node.words():
            self.rep.error("MISPLACED_ELEMENT", "<update> must be empty: <update var=\"x\"/>.", node.path, node.line)
        var = (node.attrs.get("var") or "").strip()
        d = self.vars.get(var)
        if var and d is None:
            self.rep.error("VARIABLE_MISSING", f"<update> names undeclared variable '{var}'.", node.path, node.line)
        elif var:
            self.asked.add(var)
            if d.get("source") == "system":
                self.rep.error("SYSTEM_VARIABLE_UPDATE", f"'{var}' is a system variable.", node.path, node.line)
            elif not (d.get("description") or "").strip():
                self.rep.warn("UPDATE_WITHOUT_DESCRIPTION", f"Describe '{var}': the model sees the description.", node.path, node.line)

    def tool(self, node):
        self.attrs(node, required=("name",))
        if node.elements or node.words():
            self.rep.error("MISPLACED_ELEMENT", "<tool> must be empty: <tool name=\"x\"/>.", node.path, node.line)
        name = (node.attrs.get("name") or "").strip()
        if name and self.tools is not None and name not in self.tools:
            self.rep.error("TOOL_MISSING", f"Tool '{name}' is not configured for the bot.", node.path, node.line)

    def transition(self, node, scenario, depth, parent):
        self.attrs(node, required=("go_to", "mode", "type"), optional=("when",))
        fillers = [e for e in node.elements if e.tag == "filler"]
        for e in node.elements:
            if e.tag != "filler":
                self.stray(e, f"<{e.tag}> can't be used inside <transition>.")
        if len(fillers) > 1:
            self.rep.error("MISPLACED_ELEMENT", "A <transition> has at most one <filler>.", fillers[1].path, fillers[1].line)
        if node.words():
            self.rep.error("MISPLACED_ELEMENT", "<transition> can only contain a <filler>.", node.path, node.line)
        for f in fillers[:1]:
            self.attrs(f)
            self.lines(f)
        go = (node.attrs.get("go_to") or "").strip()
        if go and go not in self.scenarios:
            self.rep.error("SCENARIO_MISSING", f"go_to '{go}' does not exist.", node.path, node.line)
        elif go:
            self.targets.add(go)
            if go == scenario:
                self.rep.error("SELF_TRANSITION", "A transition can't go to its own scenario.", node.path, node.line)
        typ, mode = (node.attrs.get("type") or "").strip(), (node.attrs.get("mode") or "").strip()
        has_when = "when" in node.attrs
        self.counts["transitions"] += 1
        self.counts["llm_exits"] += mode == "llm"
        if has_when and (typ == "variable" or mode == "auto"):
            self.transition_whens.append(node.attrs["when"])
        if not fillers and go in self.scenarios and go not in self.say_only:
            self.rep.warn("LINT_NO_FILLER", f"No <filler>: silence while '{go}' generates its first reply after the move.", node.path, node.line)
        if typ and typ not in ("inline", "variable"):
            self.rep.error("INVALID_ATTRIBUTE_VALUE", 'type is "inline" or "variable".', node.path, node.line)
        elif typ == "variable" and not (node.attrs.get("when") or "").strip():
            self.rep.error("MISSING_ATTRIBUTE", 'type="variable" needs a when.', node.path, node.line)
        elif typ == "inline" and has_when:  # contract 10.2 / editor
            self.rep.error("TRANSITION_TYPE_MISMATCH", 'A transition with a when is type="variable".', node.path, node.line)
        if not mode:
            return
        if mode not in ("llm", "auto"):
            self.rep.error("INVALID_ATTRIBUTE_VALUE", 'mode is "llm" or "auto".', node.path, node.line)
            return
        if mode == "llm":
            if has_when:
                self.rep.error("LLM_TRANSITION_WITH_WHEN", 'mode="llm" takes no when (a variable transition is always auto).', node.path, node.line)
        elif has_when:
            self.when(node, node.attrs["when"])
        elif depth == 0:
            self.rep.error("AUTO_TRANSITION_UNCONDITIONAL", 'mode="auto" needs a when, or must sit alone in an <if>/<elif>/<else>.', node.path, node.line)
        if typ == "inline" and depth > 0:  # contract 6.7: alone in branch <=> auto
            alone = len(parent.elements) == 1 and not parent.words()
            if alone and mode == "llm":
                self.rep.error("TRANSITION_MODE_MISMATCH", 'Alone in an If branch, an inline transition is mode="auto".', node.path, node.line)
            if not alone and mode == "auto":
                self.rep.error("TRANSITION_MODE_MISMATCH", 'Next to other content, an inline transition is mode="llm" (auto would drop that content).', node.path, node.line)

    def when(self, node, text):
        try:
            conds = parse_when(text)
        except WhenError as exc:
            self.rep.error(exc.code, f"{exc} (in: {text.strip()})", node.path, node.line)
            return
        if len(conds) > LIMITS["conditions"]:
            self.rep.error("TOO_MANY_CONDITIONS", f"At most {LIMITS['conditions']} conditions per when.", node.path, node.line)
        for var, op, kind, value in conds:
            self.asked.add(var)
            d = self.vars.get(var)
            if isinstance(d, dict) and d.get("source") == "extracted" and op not in ("EXISTS", "NOT_EXISTS"):
                self.counts["waits"] += 1
            if not isinstance(d, dict):
                self.rep.error("VARIABLE_MISSING", f"'{var}' in the condition is not declared.", node.path, node.line)
                continue
            problem = check_condition(var, op, kind, value, d)
            if problem:
                self.rep.error("CONDITION_TYPE_MISMATCH", problem, node.path, node.line)
            elif d.get("type") == "enum" and op not in ("EXISTS", "NOT_EXISTS"):
                if kind == "list" and len(value) > 1:
                    self.rep.error("FE_IN_LIST", f"The editor rejects {op} with several values; use "
                                   f"{var} EQUALS 'A' OR {var} EQUALS 'B' (NOT_IN: NOT_EQUALS joined by AND).", node.path, node.line)
                options = d.get("allowed_values") or []
                for v in value if kind == "list" else [value]:
                    if v.strip() not in options:
                        self.rep.error("FE_ENUM_CASE", f"The editor matches enum values case-sensitively: write {v!r} exactly as declared.", node.path, node.line)
        shape = fe_bracket_problem(text)
        if shape:
            self.rep.error("FE_BRACKETS", f"{shape} (in: {text.strip()})", node.path, node.line)

    # -- driver -------------------------------------------------------------------
    def run(self, greeting=None, ending=None):
        if not self.schema():
            return
        for name, d in self.vars.items():
            if d.get("type") == "enum":
                problem = enum_problem(d.get("allowed_values"))
                if problem:
                    self.rep.error("INVALID_ALLOWED_VALUES", problem, f"variables_schema.{name}.allowed_values")
        start = self.cfg["start"]
        if start not in self.scenarios:
            self.rep.error("SCENARIO_MISSING", f"start scenario '{start}' does not exist.", "start")
        self.targets.add(start)
        for key, text in self.cfg["global_prompt"].items():
            self.plain(text, f"global_prompt.{key}")
        interrupt_targets = {}
        for name, gt in (self.cfg.get("global_transitions") or {}).items():
            base = f"global_transitions.{name}"
            self.links(gt["when_llm"], f"{base}.when_llm")
            self.plain(gt["when_llm"], f"{base}.when_llm")
            if gt["go_to"] not in self.scenarios:
                self.rep.error("SCENARIO_MISSING", f"go_to '{gt['go_to']}' does not exist.", f"{base}.go_to")
            if gt["go_to"] in interrupt_targets:
                self.rep.error("DUPLICATE_GLOBAL_TARGET", f"'{gt['go_to']}' is already the target of "
                               f"'{interrupt_targets[gt['go_to']]}' (the editor allows one interrupt per target).", f"{base}.go_to")
            interrupt_targets.setdefault(gt["go_to"], name)
            self.targets.add(gt["go_to"])
            if "filler" in gt:
                root = parse_fragment(gt["filler"], "filler", f"{base}.filler", self.rep)
                if root is not None:
                    self.lines(root)
        for key in REQUIRED_SECTIONS:
            val = self.cfg["global_prompt"].get(key, self.cfg["global_prompt"].get("conversationStyle", ""))
            if isinstance(val, str) and val and not val.strip():
                self.rep.error("FE_GLOBAL_PROMPT_BLANK", f"The editor needs global_prompt.{key} non-blank.", f"global_prompt.{key}")
        for name, text in self.scenarios.items():
            root = parse_fragment(text, "scenario", f"scenarios.{name}", Report())
            if root is not None and not root.words() and root.elements and all(
                    e.tag in ("say", "transition") for e in root.elements):
                self.say_only.add(name)
        for name, text in self.scenarios.items():
            self.scenario(name, text)
        self.fe_prune(greeting)
        for name in self.scenarios:
            if name not in self.targets:
                self.rep.warn("UNREACHABLE_SCENARIO", "Nothing leads here and it is not start.", f"scenarios.{name}")
        for name, d in self.vars.items():
            if d.get("source") == "extracted" and name not in self.asked:
                self.rep.warn("VARIABLE_NEVER_ASKED", "Never in an <update> or a when: it can't be captured.", f"variables_schema.{name}")
        for label, msg in (("greeting", greeting), ("ending", ending)):
            for var in re.findall(r"\{\{\s*(\w+)\s*\}\}", msg or ""):
                d = self.vars.get(var)
                if d is None:
                    self.rep.error("VARIABLE_MISSING", f"{label} message uses undeclared '{var}'.", label)
                elif d.get("source") == "extracted":
                    self.rep.error("INITIAL_MESSAGE_EXTRACTED_VAR", f"{label} message can't use extracted '{var}' (empty then).", label)


    def fe_prune(self, greeting):
        """The editor drops variables its regexes don't see as used on header Save (then the save fails)."""
        texts = [v for v in self.cfg["global_prompt"].values() if isinstance(v, str)]
        texts += [t for t in self.scenarios.values() if isinstance(t, str)]
        texts += [gt.get("filler", "") for gt in (self.cfg.get("global_transitions") or {}).values()]
        texts += [greeting or ""]
        for name, d in self.vars.items():
            if d.get("source") == "system":
                continue
            n = re.escape(name)
            when_re = re.compile(r"(?:^|[\s(])%s\s+[A-Z_]" % n)
            used = any(re.search(r"\{\{\s*%s\s*\}\}" % n, t) or re.search(r'<update\b[^>]*\bvar="%s"' % n, t)
                       or when_re.search(t) for t in texts) or any(when_re.search(w) for w in self.transition_whens)
            referenced = name in self.asked or any(re.search(r"\b%s\b" % n, t) for t in texts)
            if referenced and not used:
                self.rep.error("FE_VARIABLE_PRUNED", f"The editor doesn't see '{name}' as used (only the first operand of an "
                               f"<if>/<elif> when) and deletes it on Save, then the save fails VARIABLE_MISSING. Also reference it "
                               f"elsewhere, or start that when with a space: when=\" {name} ...\".", f"variables_schema.{name}")


def validate(cfg, langs=None, tools=None, greeting=None, ending=None):
    rep = Report()
    if isinstance(cfg, dict) and isinstance(cfg.get("scenario_config"), dict):
        cfg = cfg["scenario_config"]
    if not isinstance(cfg, dict):
        rep.error("SCHEMA_INVALID", "scenario_config must be an object.")
        return rep
    Checker(cfg, langs or [], None if tools is None else set(tools), rep).run(greeting, ending)
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--languages", "--langs", dest="langs", default="", help="bot languages, primary first, e.g. en-IN,hi-IN")
    ap.add_argument("--tools", default=None, help="bot action names; omit to skip TOOL_MISSING")
    ap.add_argument("--greeting")
    ap.add_argument("--ending")
    a = ap.parse_args()
    with open(a.config, encoding="utf-8") as fh:
        cfg = json.load(fh)
    langs = [x.strip() for x in a.langs.split(",") if x.strip()]
    if not langs and isinstance(cfg.get("bot_language"), list):  # a bot_config-shaped file carries its own
        langs = cfg["bot_language"]
    a.greeting = a.greeting if a.greeting is not None else cfg.get("initial_message")
    a.ending = a.ending if a.ending is not None else cfg.get("end_message")
    tools = None if a.tools is None else [x.strip() for x in a.tools.split(",") if x.strip()]
    if not langs:
        print("note: --languages not given, language rules skipped", file=sys.stderr)
    rep = validate(cfg, langs, tools, a.greeting, a.ending)
    for kind, items in (("ERROR", rep.errors), ("WARN", rep.warnings)):
        for code, path, line, msg in items:
            print(f"{kind} {code} {path}{f':{line}' if line else ''} - {msg}")
    print(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    sys.exit(1 if rep.errors else 0)


if __name__ == "__main__":
    main()
