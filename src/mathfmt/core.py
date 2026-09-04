#!/usr/bin/env python3
"""Scan and typeset plain-text DOCX formulas as native Word OMML equations."""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from ._version import __version__
from .accents import ACCENT_CHARS
from .aliases import AliasProfile, alias_profile_metadata, validate_review_alias_profile
from .docxio import inspect_docx, parse_xml_part, write_docx
from .omml import combine_equation_array, mathml_to_omml_py
from .plugins import (
    FormulaCandidate,
    FormulaRecognizer,
    normalize_recognizers,
    recognize_with_plugins,
    recognizers_metadata,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
MML_NS = "http://www.w3.org/1998/Math/MathML"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS, "m": M_NS}

TARGET_PART_RE = re.compile(r"^word/(document|header\d+|footer\d+)\.xml$")

SUBSCRIPT_MAP = str.maketrans(
    "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ",
    "0123456789+-=()aehijklmnop rstuvx".replace(" ", ""),
)
SUPERSCRIPT_MAP = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁺": "+",
    "⁻": "-",
    "⁼": "=",
    "⁽": "(",
    "⁾": ")",
    "ⁿ": "n",
}
SUPERSCRIPT_CHARS = "".join(SUPERSCRIPT_MAP)

CODE_START_RE = re.compile(
    r"^(?:%|#|pkg\s|clear\b|close\b|plot\b|grid\b|xlabel\b|ylabel\b|"
    r"title\b|legend\b|hold\b|for\b|while\b|if\b|function\b|import\b|from\b)",
    re.IGNORECASE,
)
FORMULA_ANCHOR_RE = re.compile(r"(?:=|≠|<=|>=|!=|→|⇒|⇌|<->|->|±|\+/-|√|sqrt|lim|∫|∑|∏|∈|∉|⊂|⊆|⊃|⊇|∝|≡|≅)")
MATH_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    "₀₁₂₃₄₅₆₇₈₉ₚᵥₜ⁰¹²³⁴⁵⁶⁷⁸⁹+-*/^=<>!~→⇒⇌±≠≤≥≈≅√∞ΔπΓ"
    "ℝℂℕℤℚℙℍℓ∈∉⊂⊆⊃⊇∪∩∧∨⊕⊗∝≡"
    "()[]{}⟨⟩.,'′˙¨·×÷_ \t∫∑∏∂;|"
    "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρστυφχψω"
)
TRIM_PUNCT = " \t,，.。;；:："

CHEMICAL_ELEMENTS = frozenset(
    {
        "Ac",
        "Ag",
        "Al",
        "Am",
        "Ar",
        "As",
        "At",
        "Au",
        "B",
        "Ba",
        "Be",
        "Bh",
        "Bi",
        "Bk",
        "Br",
        "C",
        "Ca",
        "Cd",
        "Ce",
        "Cf",
        "Cl",
        "Cm",
        "Cn",
        "Co",
        "Cr",
        "Cs",
        "Cu",
        "Ds",
        "Db",
        "Dy",
        "Er",
        "Es",
        "Eu",
        "F",
        "Fe",
        "Fl",
        "Fm",
        "Fr",
        "Ga",
        "Gd",
        "Ge",
        "H",
        "He",
        "Hf",
        "Hg",
        "Ho",
        "Hs",
        "I",
        "In",
        "Ir",
        "K",
        "Kr",
        "La",
        "Li",
        "Lr",
        "Lu",
        "Lv",
        "Mc",
        "Md",
        "Mg",
        "Mn",
        "Mo",
        "Mt",
        "N",
        "Na",
        "Nb",
        "Nd",
        "Ne",
        "Nh",
        "Ni",
        "No",
        "Np",
        "O",
        "Og",
        "Os",
        "P",
        "Pa",
        "Pb",
        "Pd",
        "Pm",
        "Po",
        "Pr",
        "Pt",
        "Pu",
        "Ra",
        "Rb",
        "Re",
        "Rf",
        "Rg",
        "Rh",
        "Rn",
        "Ru",
        "S",
        "Sb",
        "Sc",
        "Se",
        "Sg",
        "Si",
        "Sm",
        "Sn",
        "Sr",
        "Ta",
        "Tb",
        "Tc",
        "Te",
        "Th",
        "Ti",
        "Tl",
        "Tm",
        "Ts",
        "U",
        "V",
        "W",
        "Xe",
        "Y",
        "Yb",
        "Zn",
        "Zr",
    }
)
CHEM_STATE_RE = re.compile(r"\((aq|g|l|s)\)$")
CHEM_ARROW_RE = re.compile(r"(?P<arrow><->|->|=>|⇌|→|⇒)(?:\s*\[(?P<annotation>[A-Za-z][A-Za-z0-9 +\-]*)\])?")
CHEM_ARROW_SYMBOLS = {"<->": "⇌", "⇌": "⇌", "->": "→", "→": "→", "=>": "⇒", "⇒": "⇒"}
_CHEM_FORMULA_FRAGMENT = r"(?:[A-Z][a-z]?\d*|\((?:[A-Z][a-z]?\d*)+\)\d*)+"
_CHEM_TERM_FRAGMENT = rf"(?:[1-9]\d*\s*)?{_CHEM_FORMULA_FRAGMENT}(?:\((?:aq|g|l|s)\))?"
_CHEM_SIDE_FRAGMENT = rf"{_CHEM_TERM_FRAGMENT}(?:\s*\+\s*{_CHEM_TERM_FRAGMENT})*"
CHEM_REACTION_SCAN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<reaction>{_CHEM_SIDE_FRAGMENT}\s*"
    rf"(?:<->|->|=>|⇌|→|⇒)(?:\s*\[[^\]\r\n]+\])?\s*{_CHEM_SIDE_FRAGMENT})(?![A-Za-z0-9])"
)
CHEM_FORMULA_SCAN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<formula>{_CHEM_FORMULA_FRAGMENT}(?:\((?:aq|g|l|s)\))?)(?![A-Za-z0-9])"
)

_PHYSICS_IDENTIFIER = r"(?:[A-Za-z][A-Za-z0-9]*|[Α-Ωα-ω])"
_PHYSICS_INDEX = rf"(?:{_PHYSICS_IDENTIFIER}|\d+)"
PARTIAL_DERIVATIVE_SCAN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<partial>(?:partial\s+{_PHYSICS_IDENTIFIER}\s*/\s*"
    rf"partial\s+{_PHYSICS_IDENTIFIER}|∂\s*{_PHYSICS_IDENTIFIER}\s*/\s*∂\s*{_PHYSICS_IDENTIFIER}))"
    rf"(?![A-Za-z0-9])"
)
TENSOR_SCAN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<tensor>{_PHYSICS_IDENTIFIER}_"
    rf"(?:{_PHYSICS_INDEX}|\{{{_PHYSICS_INDEX}\}})\^"
    rf"(?:{_PHYSICS_INDEX}|\{{{_PHYSICS_INDEX}\}}))(?![A-Za-z0-9])"
)
BRAKET_SCAN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<braket>(?:"
    rf"(?:<|⟨)\s*{_PHYSICS_IDENTIFIER}\s*\|\s*{_PHYSICS_IDENTIFIER}\s*(?:>|⟩)|"
    rf"bra\(\s*{_PHYSICS_IDENTIFIER}\s*\)\s+ket\(\s*{_PHYSICS_IDENTIFIER}\s*\)|"
    rf"(?:bra|ket)\(\s*{_PHYSICS_IDENTIFIER}\s*\)))"
    rf"(?![A-Za-z0-9])"
)


def qname(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


def mml(local: str, text: str | None = None, **attrs: str) -> etree._Element:
    element = etree.Element(qname(MML_NS, local), **attrs)
    if text is not None:
        element.text = text
    return element


def mrow(*children: etree._Element) -> etree._Element:
    row = mml("mrow")
    for child in children:
        row.append(child)
    return row


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    start: int
    end: int


@dataclass
class Node:
    kind: str
    value: str | None = None
    children: tuple[Node, ...] = ()
    meta: dict[str, str] | None = None


@dataclass
class ChemicalFormula:
    element: etree._Element
    element_count: int
    has_subscript: bool = False
    has_group: bool = False
    has_multiletter_element: bool = False

    @property
    def distinctive(self) -> bool:
        return self.element_count >= 2 or self.has_subscript or self.has_group or self.has_multiletter_element


CandidateSpan = FormulaCandidate


class FormulaError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        position: int | None = None,
        expected: str | None = None,
        found: str | None = None,
        source: str | None = None,
    ) -> None:
        self.position = position
        self.expected = expected
        self.found = found
        self.source = source
        details = message
        if position is not None:
            details = f"{details} at column {position + 1}"
            if source:
                start = max(0, position - 12)
                end = min(len(source), position + 12)
                snippet = source[start:end]
                caret = " " * max(0, position - start) + "^"
                details = f"{details}: {snippet!r}\n{caret}"
        super().__init__(details)

    def to_dict(self) -> dict[str, object]:
        details: dict[str, object] = {"message": str(self)}
        if self.position is not None:
            details["position"] = self.position
            details["column"] = self.position + 1
        if self.expected:
            details["expected"] = self.expected
        if self.found:
            details["found"] = self.found
        if self.source:
            start = max(0, (self.position or 0) - 12)
            end = min(len(self.source), (self.position or 0) + 12)
            details["context"] = self.source[start:end]
        hint = _suggest_fix(self.expected)
        if hint:
            details["hint"] = hint
        return details


def _suggest_fix(expected: str | None) -> str | None:
    """Best-effort, human-readable suggestion for a recognized FormulaError shape.

    Matches on the same literal ``expected`` strings the parser already raises
    (see the ``FormulaError(..., expected=...)`` call sites above); an
    unrecognized or dynamic ``expected`` value yields no hint rather than a
    guess, so this never contradicts the actual error. Matches are exact, not
    prefix/substring, so one rule's wording can't accidentally catch a
    different error that happens to start the same way.
    """
    if not expected:
        return None
    # `expect("RPAREN")` reports the token *kind* (shared by ), ], and }) for a
    # bracket that's missing entirely; a present-but-wrong closer instead
    # reports the specific expected character — both mean the same mistake.
    if expected in {"RPAREN", ")", "]", "}", "(", "[", "{"}:
        return "Check for a missing or mismatched bracket — every '(', '[', '{' needs a matching closer."
    if expected == "if":
        return "Each cases()/{...} branch needs the form 'value if condition' — add the missing 'if'."
    if expected == "condition":
        return "Add a condition after 'if' in this branch, e.g. 'x if x>=0'."
    if expected == "; or )":
        return "Separate cases/piecewise branches with ';' and close the group with ')'."
    if expected in {"branch expression", "expression, condition"}:
        return "Each cases()/{...} branch needs an expression before 'if', e.g. 'x^2 if x>=0'."
    if "comma-separated argument" in expected:
        return "Check the comma count against the required argument list: " + expected + "."
    if expected == "end of formula":
        return "There is extra text after a complete formula — remove it or split into two formulas."
    if expected == "chemical element or parenthesized chemical group":
        return "Check element symbols and capitalization in the chemical formula, e.g. 'Na' not 'NA'."
    if expected == "chemical formula":
        return "Each side of the reaction arrow needs at least one recognizable chemical formula."
    if expected == "one reaction arrow":
        return (
            "A single reaction may only use one arrow (->, <->, or =>); "
            "split multi-arrow text into separate formulas."
        )
    if expected == "]] or ,":
        return "Separate matrix entries with ',' and rows with ';', closing the matrix with ']]'."
    if expected == "accent kind":
        return f"An accent must be one of: {', '.join(ACCENT_CHARS)} — e.g. accent(x,bar)."
    if expected == "number, identifier, function, matrix, or grouped expression":
        return "An operand is missing here — check for a stray operator or an empty group."
    if expected == "number, identifier, operator, or grouping symbol":
        return "This character isn't recognized — check for a typo or an unsupported symbol."
    return None


# ∇ and ∓ are tokenizable but deliberately absent from MATH_CHARS: they parse
# when they reach a formula (via a LaTeX macro or an explicit $…$ span) but are
# never picked up by generic candidate discovery. ∂ is the reverse — it IS in
# MATH_CHARS, so making it tokenizable on its own would turn today's reviewable
# parse error for shapes like ∂^2u/∂x^2 into a silently wrong conversion. Bare ∂
# therefore stays untokenizable; ∂f/∂x is handled earlier, by preprocess_formula.
TOKEN_RE = re.compile(
    r"\s*(?:"
    r"(?P<MATRIX_OPEN>\[\[)|"
    r"(?P<MATRIX_CLOSE>\]\])|"
    r"(?P<NUMBER>\d+(?:\.\d+)?)|"
    r"(?P<IF>if\b)|"
    r"(?P<IDENT>sqrt|lim|exp|sin|cos|tan|Delta|pi|inf|e[pv]|pPAIR|DERV\d+|[A-Za-z][A-Za-z0-9]*|[Α-Ωα-ω∞∫∑∏ℝℂℕℤℚℙℍℓ∇])|"
    r"(?P<OP><->|<=|>=|!=|<<|>>|~=|->|=>|\+/-|[+\-*/^=<>!±∓≠≤≥≈≅→⇒⇌·×÷_∈∉⊂⊆⊃⊇∪∩∧∨⊕⊗∝≡])|"
    r"(?P<LPAREN>[\(\[\{])|(?P<RPAREN>[\)\]\}])|(?P<COMMA>,)|(?P<SEMI>;)|"
    r"(?P<ELLIPSIS>…)"
    r")"
)


def preprocess_formula(source: str) -> tuple[str, dict[str, tuple[int, str, str]]]:
    text = source.strip()
    derivatives: dict[str, tuple[int, str, str]] = {}

    # Normalize documented physics shorthand into explicit parser functions.
    text = re.sub(
        rf"\bpartial\s+({_PHYSICS_IDENTIFIER})\s*/\s*partial\s+({_PHYSICS_IDENTIFIER})\b",
        r"partial(\1,\2)",
        text,
    )
    text = re.sub(
        rf"∂\s*({_PHYSICS_IDENTIFIER})\s*/\s*∂\s*({_PHYSICS_IDENTIFIER})",
        r"partial(\1,\2)",
        text,
    )
    text = re.sub(
        rf"(?:<|⟨)\s*({_PHYSICS_IDENTIFIER})\s*\|\s*({_PHYSICS_IDENTIFIER})\s*(?:>|⟩)",
        r"braket(\1,\2)",
        text,
    )

    leibniz_patterns = [
        (2, re.compile(r"\bd(?:\^?2|²)([A-Za-z])\(([^()]*)\)/d([A-Za-z])(?:\^?2|²)")),
        (1, re.compile(r"\bd([A-Za-z])\(([^()]*)\)/d([A-Za-z])")),
    ]
    for order, pattern in leibniz_patterns:
        while True:
            match = pattern.search(text)
            if not match:
                break
            key = f"DERV{len(derivatives)}"
            derivatives[key] = (order, match.group(1), match.group(3))
            text = text[: match.start()] + key + text[match.end() :]

    derivative_patterns = [
        (2, re.compile(r"([A-Za-z])(?:''|¨)\(([^()]*)\)")),
        (1, re.compile(r"([A-Za-z])(?:'|′|˙)\(([^()]*)\)")),
    ]
    for order, pattern in derivative_patterns:
        while True:
            match = pattern.search(text)
            if not match:
                break
            key = f"DERV{len(derivatives)}"
            derivatives[key] = (order, match.group(1), match.group(2))
            text = text[: match.start()] + key + text[match.end() :]

    text = text.replace("limₚ→0", "lim(p->0)").replace("limₜ→∞", "lim(t->inf)")
    text = re.sub(r"lim_\{([^}]+)\}", r"lim(\1)", text)
    text = re.sub(r"\b∑_\{([^{}]+)\}\^\{([^{}]+)\}", r"sum(\1,\2,", text)
    text = re.sub(
        r"([A-Za-z0-9)\]])([" + re.escape(SUPERSCRIPT_CHARS) + r"]+)",
        lambda m: m.group(1) + "^" + "".join(SUPERSCRIPT_MAP[c] for c in m.group(2)),
        text,
    )
    text = text.translate(SUBSCRIPT_MAP)
    text = re.sub(r"\bp1\s*,\s*2\b", "pPAIR", text)
    text = text.replace("√", "sqrt").replace("+/-", "±")
    text = text.replace("!=", "≠").replace("<=", "≤").replace(">=", "≥")
    text = text.replace("<->", "⇌").replace("->", "→").replace("=>", "⇒").replace("...", "…")
    text = text.replace("×", "*").replace("·", "*").replace("÷", "/")
    text = re.sub(r"(?:Γ|1)\(t\)", "u(t)", text)
    text = re.sub(r"\bDelta\b", "Δ", text)
    text = re.sub(r"\binf\b", "∞", text)
    text = re.sub(r"\bpi\b", "π", text)
    text = re.sub(r"e\^\{([^{}]+)\}", r"e^(\1)", text)
    return text, derivatives


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    while position < len(text):
        match = TOKEN_RE.match(text, position)
        if not match:
            if text[position:].strip() == "":
                break
            raise FormulaError(
                f"Unrecognized formula text near: {text[position : position + 24]!r}",
                position=position,
                expected="number, identifier, operator, or grouping symbol",
                found=text[position],
                source=text,
            )
        kind = match.lastgroup
        if kind is None:
            raise FormulaError("Tokenizer produced an empty token", position=position, source=text)
        tokens.append(Token(kind, match.group(kind), match.start(kind), match.end(kind)))
        position = match.end()
    tokens.append(Token("EOF", "", len(text), len(text)))
    return tokens


def _serialize_ast(node: Node) -> str:
    if node.kind in {"number", "identifier"}:
        return node.value or ""
    if node.kind == "sequence":
        return ",".join(_serialize_ast(c) for c in node.children)
    if node.kind == "binary":
        if node.value == "implicit":
            return _serialize_ast(node.children[0]) + _serialize_ast(node.children[1])
        return _serialize_ast(node.children[0]) + (node.value or "") + _serialize_ast(node.children[1])
    return ""


class Parser:
    def __init__(
        self,
        tokens: Sequence[Token],
        derivatives: dict[str, tuple[int, str, str]],
        source: str,
        aliases: Mapping[str, str] | None = None,
    ):
        self.tokens = tokens
        self.derivatives = derivatives
        self.source = source
        self.aliases = aliases or {}
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def accept(self, kind: str, value: str | None = None) -> Token | None:
        if self.current.kind == kind and (value is None or self.current.value == value):
            return self.advance()
        return None

    def expect(self, kind: str) -> Token:
        token = self.accept(kind)
        if token is None:
            raise FormulaError(
                f"Expected {kind}, got {self.current.kind} {self.current.value!r}",
                position=self.current.start,
                expected=kind,
                found=self.current.value or self.current.kind,
                source=self.source,
            )
        return token

    def parse(self) -> Node:
        node = self.parse_sequence()
        if self.current.kind != "EOF":
            raise FormulaError(
                f"Unexpected token: {self.current.value!r}",
                position=self.current.start,
                expected="end of formula",
                found=self.current.value,
                source=self.source,
            )
        return node

    def parse_sequence(self, semi_is_branch: bool = False) -> Node:
        nodes = [self.parse_relation()]
        while self.accept("COMMA"):
            nodes.append(self.parse_relation())
        if semi_is_branch and self.current.kind == "SEMI":
            branches = [self._piecewise_branch(nodes, 1)]
            branch_number = 2
            while self.accept("SEMI"):
                if self.current.kind == "RPAREN":
                    raise FormulaError(
                        f"Piecewise branch {branch_number} is empty",
                        position=self.current.start,
                        expected="branch expression",
                        found=self.current.value,
                        source=self.source,
                    )
                branch_nodes = [self.parse_relation()]
                while self.accept("COMMA"):
                    branch_nodes.append(self.parse_relation())
                branches.append(self._piecewise_branch(branch_nodes, branch_number))
                branch_number += 1
            return Node("piecewise", children=tuple(branches))
        return nodes[0] if len(nodes) == 1 else Node("sequence", children=tuple(nodes))

    def _piecewise_branch(self, nodes: list[Node], branch_number: int) -> Node:
        if len(nodes) != 2:
            raise FormulaError(
                f"Piecewise branch {branch_number} must contain an expression and condition separated by ','",
                position=self.current.start,
                expected="expression, condition",
                found=self.current.value or self.current.kind,
                source=self.source,
            )
        return Node("case", children=(nodes[0], nodes[1]))

    def parse_relation(self) -> Node:
        node = self.parse_add()
        while self.current.kind == "OP" and self.current.value in {
            "=",
            "<",
            ">",
            "≤",
            "≥",
            "≠",
            "~=",
            "→",
            "⇒",
            "⇌",
            "∈",
            "∉",
            "⊂",
            "⊆",
            "⊃",
            "⊇",
            "∝",
            "≡",
            "≅",
        }:
            op = self.advance().value
            node = Node("binary", op, (node, self.parse_add()))
        return node

    def parse_add(self) -> Node:
        node = self.parse_mul()
        while self.current.kind == "OP" and self.current.value in {
            "+",
            "-",
            "±",
            "∓",
            "∪",
            "∩",
            "∧",
            "∨",
            "⊕",
        }:
            op = self.advance().value
            node = Node("binary", op, (node, self.parse_mul()))
        return node

    def starts_atom(self) -> bool:
        return self.current.kind in {"NUMBER", "IDENT", "LPAREN", "MATRIX_OPEN"}

    def parse_mul(self) -> Node:
        node = self.parse_power()
        while True:
            if self.current.kind == "OP" and self.current.value in {"*", "·", "×", "/", "÷", "⊗"}:
                op = self.advance().value
                normalized = "/" if op in {"/", "÷"} else "*" if op in {"*", "·", "×"} else op
                node = Node("binary", normalized, (node, self.parse_power()))
            elif self.starts_atom() and self.current.kind != "MATRIX_OPEN":
                right = self.parse_power()
                if node.kind == "bra" and right.kind == "ket":
                    node = Node("braket", children=(node.children[0], right.children[0]))
                else:
                    node = Node("binary", "implicit", (node, right))
            else:
                break
        return node

    def parse_power(self) -> Node:
        node = self.parse_subsup()
        if self.current.kind == "OP" and self.current.value == "^":
            self.advance()
            node = Node("power", children=(node, self.parse_power()))
        if self.current.kind == "OP" and self.current.value == "!":
            self.advance()
            node = Node("factorial", children=(node,))
        return node

    def parse_subsup(self) -> Node:
        node = self.parse_unary()
        if self.current.kind == "OP" and self.current.value == "_":
            self.advance()
            sub = self.parse_unary()
            if self.current.kind == "OP" and self.current.value == "^":
                self.advance()
                sup = self.parse_unary()
                return Node("subsup", children=(node, sub, sup))
            return Node("sub", children=(node, sub))
        return node

    def parse_unary(self) -> Node:
        if self.current.kind == "OP" and self.current.value in {"+", "-", "±", "∓"}:
            return Node("unary", self.advance().value, (self.parse_unary(),))
        return self.parse_atom()

    def parse_group(self) -> Node:
        opener = self.expect("LPAREN").value
        closer = {"(": ")", "[": "]", "{": "}"}[opener]
        child = self.parse_sequence(semi_is_branch=(opener == "{"))
        token = self.expect("RPAREN")
        if token.value != closer:
            raise FormulaError(
                f"Mismatched group: {opener}{token.value}",
                position=token.start,
                expected=closer,
                found=token.value,
                source=self.source,
            )
        if child.kind == "piecewise":
            return child
        if opener == "[" and child.kind == "sequence":
            return Node("vector", children=child.children)
        return Node("group", opener + closer, (child,))

    def _parse_nary(self, name: str) -> Node:
        return Node("nary", name)

    def _parse_call_arguments(self, name: str, token: Token, expected_count: int) -> tuple[Node, ...]:
        group = self.parse_group()
        inner = group.children[0]
        arguments = inner.children if inner.kind == "sequence" else (inner,)
        if len(arguments) != expected_count:
            raise FormulaError(
                f"{name} requires {expected_count} argument{'s' if expected_count != 1 else ''}",
                position=token.start,
                expected=f"{expected_count} comma-separated argument{'s' if expected_count != 1 else ''}",
                found=str(len(arguments)),
                source=self.source,
            )
        return tuple(arguments)

    def _parse_physics_function(self, name: str, token: Token) -> Node:
        expected_count = 2 if name in {"partial", "braket"} else 1
        arguments = self._parse_call_arguments(name, token, expected_count)
        kind = "partial_derivative" if name == "partial" else name
        return Node(kind, children=arguments)

    def _parse_accent(self, token: Token) -> Node:
        arguments = self._parse_call_arguments("accent", token, 2)
        kind_node = arguments[1]
        if kind_node.kind == "identifier":
            kind = kind_node.value
        elif kind_node.kind == "alias":
            # An alias must not shadow an accent kind: latex.py generates
            # accent(x,hat) internally, so a user profile defining "hat" would
            # otherwise break \hat{x} with an error mentioning neither.
            kind = (kind_node.meta or {}).get("name")
        else:
            kind = None
        if kind not in ACCENT_CHARS:
            raise FormulaError(
                f"Unknown accent kind: {kind_node.value or kind_node.kind}",
                position=token.start,
                expected="accent kind",
                found=str(kind_node.value or kind_node.kind),
                source=self.source,
            )
        return Node("accent", kind, (arguments[0],))

    def _parse_root(self, token: Token) -> Node:
        arguments = self._parse_call_arguments("root", token, 2)
        return Node("root", children=arguments)

    def _parse_cases(self) -> Node:
        opener = self.expect("LPAREN")
        if opener.value != "(":
            raise FormulaError(
                "cases must use parentheses",
                position=opener.start,
                expected="(",
                found=opener.value,
                source=self.source,
            )
        if self.current.kind == "RPAREN":
            raise FormulaError(
                "cases branch 1 is empty",
                position=self.current.start,
                expected="branch expression",
                found=self.current.value,
                source=self.source,
            )

        branches: list[Node] = []
        branch_number = 1
        while True:
            expression = self.parse_relation()
            if self.accept("IF") is None:
                raise FormulaError(
                    f"Expected 'if' in cases branch {branch_number}",
                    position=self.current.start,
                    expected="if",
                    found=self.current.value or self.current.kind,
                    source=self.source,
                )
            if self.current.kind in {"SEMI", "RPAREN", "EOF"}:
                raise FormulaError(
                    f"Missing condition in cases branch {branch_number}",
                    position=self.current.start,
                    expected="condition",
                    found=self.current.value or self.current.kind,
                    source=self.source,
                )
            condition = self.parse_relation()
            branches.append(Node("case", children=(expression, condition)))

            if self.accept("SEMI"):
                branch_number += 1
                if self.current.kind == "RPAREN":
                    raise FormulaError(
                        f"cases branch {branch_number} is empty",
                        position=self.current.start,
                        expected="branch expression",
                        found=self.current.value,
                        source=self.source,
                    )
                continue
            if self.current.kind == "RPAREN" and self.current.value == ")":
                self.advance()
                return Node("piecewise", children=tuple(branches))
            raise FormulaError(
                f"Expected ';' or ')' after cases branch {branch_number}",
                position=self.current.start,
                expected="; or )",
                found=self.current.value or self.current.kind,
                source=self.source,
            )

    def parse_atom(self) -> Node:
        if token := self.accept("MATRIX_OPEN"):
            return self._parse_matrix()
        if token := self.accept("NUMBER"):
            return Node("number", token.value)
        if token := self.accept("ELLIPSIS"):
            return Node("identifier", "…")
        if self.current.kind == "LPAREN":
            return self.parse_group()
        if token := self.accept("IDENT"):
            name = token.value
            if name in self.derivatives:
                order, variable, argument = self.derivatives[name]
                return Node(
                    "derivative",
                    children=(Node("identifier", variable), Node("identifier", argument)),
                    meta={"order": str(order)},
                )
            if name in self.aliases:
                return Node("alias", self.aliases[name], meta={"name": name})
            if name in {"∫", "∏", "∑"}:
                return self._parse_nary(name)
            if name in {"int", "sum", "prod"}:
                if self.current.kind == "LPAREN":
                    bounds = self.parse_group()
                    body = self.parse_add()
                    return Node("nary", name, children=(bounds, body))
                return Node("identifier", name)
            if name == "cases" and self.current.kind == "LPAREN":
                return self._parse_cases()
            if name in {"partial", "bra", "ket", "braket"} and self.current.kind == "LPAREN":
                return self._parse_physics_function(name, token)
            if name == "accent" and self.current.kind == "LPAREN":
                return self._parse_accent(token)
            if name == "root" and self.current.kind == "LPAREN":
                return self._parse_root(token)
            if self.current.kind == "LPAREN":
                group = self.parse_group()
                if name in {"sqrt", "√"}:
                    return Node("sqrt", children=group.children)
                if name == "lim":
                    return Node("limit", children=group.children)
                if group.kind == "vector":
                    # parse_group() returns a bare "vector" node (its
                    # comma-separated elements unwrapped directly into
                    # children) for a [a,b,...] group, unlike "(" and "{",
                    # which always wrap their content in one "group" child.
                    # Treating group.children as a call's argument list here
                    # would silently drop every element after the first --
                    # fall back to implicit multiplication instead, exactly
                    # what parse_mul would have produced had this atom not
                    # consumed the bracket. This also keeps the brackets
                    # square instead of forcing them to "()".
                    return Node("binary", "implicit", (Node("identifier", name), group))
                return Node("function", name, group.children)
            return Node("identifier", name)
        raise FormulaError(
            f"Expected formula atom, got {self.current.kind} {self.current.value!r}",
            position=self.current.start,
            expected="number, identifier, function, matrix, or grouped expression",
            found=self.current.value or self.current.kind,
            source=self.source,
        )

    def _parse_matrix(self) -> Node:
        rows: list[Node] = []
        row = self.parse_sequence()
        rows.append(row)
        while self.accept("MATRIX_CLOSE") is None:
            self.accept("RPAREN")
            if self.accept("COMMA") or self.accept("SEMI"):
                self.accept("LPAREN")
                row = self.parse_sequence()
                rows.append(row)
            elif self.accept("MATRIX_CLOSE"):
                break
            else:
                raise FormulaError(
                    "Expected ]] or , between matrix rows",
                    position=self.current.start,
                    expected="]] or ,",
                    found=self.current.value or self.current.kind,
                    source=self.source,
                )
        return Node("matrix", children=tuple(rows))


def identifier_mathml(value: str) -> etree._Element:
    if value in {"∞", "inf"}:
        return mml("mo", "∞")
    greek = {"Delta": "Δ", "Δ": "Δ", "pi": "π", "π": "π"}
    if value in greek:
        return mml("mi", greek[value])
    if value == "pPAIR":
        sub = mml("msub")
        sub.append(mml("mi", "p"))
        sub.append(mrow(mml("mn", "1"), mml("mo", ","), mml("mn", "2")))
        return sub
    match = re.fullmatch(r"([A-Za-z])([0-9]+|[pv])", value)
    if match:
        sub = mml("msub")
        sub.append(mml("mi", match.group(1)))
        suffix = match.group(2)
        sub.append(mml("mn" if suffix.isdigit() else "mi", suffix))
        return sub
    return mml("mi", value)


def derivative_mathml(node: Node) -> etree._Element:
    order = int((node.meta or {}).get("order", "1"))
    variable = node_to_mathml(node.children[0])
    argument = node_to_mathml(node.children[1])
    function = mrow(variable, fenced(argument, "()"))
    numerator_d = mml("mi", "d")
    if order > 1:
        power = mml("msup")
        power.append(numerator_d)
        power.append(mml("mn", str(order)))
        numerator_d = power
    numerator = mrow(numerator_d, function)
    denominator_variable = node_to_mathml(node.children[1])
    if order > 1:
        power = mml("msup")
        power.append(denominator_variable)
        power.append(mml("mn", str(order)))
        denominator_variable = power
    denominator = mrow(mml("mi", "d"), denominator_variable)
    fraction = mml("mfrac")
    fraction.extend([numerator, denominator])
    return fraction


def partial_derivative_mathml(node: Node) -> etree._Element:
    fraction = mml("mfrac")
    numerator = mrow(mml("mo", "∂"), node_to_mathml(node.children[0]))
    denominator = mrow(mml("mo", "∂"), node_to_mathml(node.children[1]))
    fraction.extend([numerator, denominator])
    return fraction


def fenced(child: etree._Element, brackets: str) -> etree._Element:
    element = mml("mfenced", open=brackets[0], close=brackets[1])
    element.append(child)
    return element


def _script_mathml(node: Node) -> etree._Element:
    if node.kind == "group":
        node = node.children[0]
    return node_to_mathml(node)


def node_to_mathml(node: Node) -> etree._Element:
    if node.kind == "number":
        return mml("mn", node.value or "")
    if node.kind == "identifier":
        return identifier_mathml(node.value or "")
    if node.kind == "alias":
        value = node.value or ""
        element = "mi" if value and unicodedata.category(value).startswith("L") else "mo"
        return mml(element, value)
    if node.kind == "derivative":
        return derivative_mathml(node)
    if node.kind == "partial_derivative":
        return partial_derivative_mathml(node)
    if node.kind == "bra":
        return fenced(node_to_mathml(node.children[0]), "⟨|")
    if node.kind == "ket":
        return fenced(node_to_mathml(node.children[0]), "|⟩")
    if node.kind == "braket":
        content = mrow(
            node_to_mathml(node.children[0]),
            mml("mo", "|"),
            node_to_mathml(node.children[1]),
        )
        return fenced(content, "⟨⟩")
    if node.kind == "group":
        return fenced(node_to_mathml(node.children[0]), node.value or "()")
    if node.kind == "sqrt":
        root = mml("msqrt")
        root.append(node_to_mathml(node.children[0]))
        return root
    if node.kind == "root":
        mroot = mml("mroot")
        mroot.append(node_to_mathml(node.children[0]))
        mroot.append(node_to_mathml(node.children[1]))
        return mroot
    if node.kind == "accent":
        over = mml("mover", accent="true")
        over.append(node_to_mathml(node.children[0]))
        over.append(mml("mo", ACCENT_CHARS[node.value or "bar"]))
        return over
    if node.kind == "function":
        return mrow(identifier_mathml(node.value or ""), fenced(node_to_mathml(node.children[0]), "()"))
    if node.kind == "limit":
        under = mml("munder")
        under.append(mml("mi", "lim"))
        under.append(node_to_mathml(node.children[0]))
        return under
    if node.kind == "unary":
        return mrow(mml("mo", node.value or ""), node_to_mathml(node.children[0]))
    if node.kind == "power":
        power = mml("msup")
        exponent = node.children[1]
        power.extend([node_to_mathml(node.children[0]), _script_mathml(exponent)])
        return power
    if node.kind == "binary":
        left = node_to_mathml(node.children[0])
        right = node_to_mathml(node.children[1])
        if node.value == "/":
            left_node, right_node = node.children
            if left_node.kind == "group":
                left = node_to_mathml(left_node.children[0])
            if right_node.kind == "group":
                right = node_to_mathml(right_node.children[0])
            fraction = mml("mfrac")
            fraction.extend([left, right])
            return fraction
        if node.value in {"*", "implicit"}:
            return mrow(left, mml("mo", "\u2062"), right)
        symbols = {"~=": "≈"}
        return mrow(left, mml("mo", symbols.get(node.value or "", node.value or "")), right)
    if node.kind == "sequence":
        row = mml("mrow")
        for index, child in enumerate(node.children):
            if index:
                row.append(mml("mo", ","))
            row.append(node_to_mathml(child))
        return row
    if node.kind == "vector":
        row = mml("mrow")
        for index, child in enumerate(node.children):
            if index:
                row.append(mml("mo", ","))
            row.append(node_to_mathml(child))
        return fenced(row, "[]")
    if node.kind == "matrix":
        table = mml("mtable")
        for row_node in node.children:
            tr = mml("mtr")
            items = row_node.children if row_node.kind == "sequence" else (row_node,)
            for item in items:
                td = mml("mtd")
                td.append(node_to_mathml(item))
                tr.append(td)
            table.append(tr)
        return fenced(table, "[]")
    if node.kind == "sub":
        sub = mml("msub")
        sub.append(node_to_mathml(node.children[0]))
        sub.append(_script_mathml(node.children[1]))
        return sub
    if node.kind == "subsup":
        ss = mml("msubsup")
        ss.append(node_to_mathml(node.children[0]))
        ss.append(_script_mathml(node.children[1]))
        ss.append(_script_mathml(node.children[2]))
        return ss
    if node.kind == "nary":
        return _nary_mathml(node)
    if node.kind == "factorial":
        return mrow(node_to_mathml(node.children[0]), mml("mo", "!"))
    if node.kind == "piecewise":
        table = mml("mtable", columnalign="left left")
        for branch in node.children:
            if branch.kind not in {"case", "sequence"} or len(branch.children) != 2:
                raise FormulaError("Piecewise branches require expression and condition pairs")
            tr = mml("mtr")
            expression = mml("mtd")
            expression.append(node_to_mathml(branch.children[0]))
            condition = mml("mtd")
            condition.append(mrow(mml("mtext", "if\u00a0"), node_to_mathml(branch.children[1])))
            tr.extend([expression, condition])
            table.append(tr)
        piecewise = mml("mfenced", open="{", close="")
        piecewise.append(table)
        return piecewise
    raise FormulaError(f"Unsupported AST node: {node.kind}")


def _nary_mathml(node: Node) -> etree._Element:
    """Generate MathML for n-ary operators: int/sum/prod."""
    name = node.value or "int"
    op_map = {"int": "∫", "sum": "∑", "prod": "∏", "∫": "∫", "∑": "∑", "∏": "∏"}
    op_char = op_map.get(name, "∫")

    # Backward compatibility: bare Unicode nary (∫ / ∑ / ∏) without children
    if not node.children:
        return mml("mo", op_char)

    bounds_node = node.children[0]
    body = node_to_mathml(node.children[1])

    # Unwrap group and sequence wrappers to reach the actual bound items
    inner = bounds_node
    while inner.kind == "group" and inner.children:
        inner = inner.children[0]
    bound_items = inner.children if inner.kind == "sequence" else (inner,)
    has_limits = len(bound_items) >= 2

    if name == "sum":
        op_mathml = mml("munderover") if has_limits else mml("mo", op_char)
        if has_limits:
            op_mathml.append(mml("mo", op_char))
            op_mathml.append(node_to_mathml(bound_items[0]))
            op_mathml.append(node_to_mathml(bound_items[1]))
        return mrow(op_mathml, body)

    if name == "prod":
        op_mathml = mml("munderover") if has_limits else mml("mo", op_char)
        if has_limits:
            op_mathml.append(mml("mo", op_char))
            op_mathml.append(node_to_mathml(bound_items[0]))
            op_mathml.append(node_to_mathml(bound_items[1]))
        return mrow(op_mathml, body)

    if name == "int":
        if has_limits:
            integral = mml("msubsup")
            integral.append(mml("mo", op_char))
            integral.append(node_to_mathml(bound_items[0]))
            integral.append(node_to_mathml(bound_items[1]))
            return mrow(integral, body)
        integrand = node_to_mathml(bound_items[0])
        return mrow(mml("mo", op_char), integrand, body)

    return mrow(mml("mo", op_char), body)


def _parse_chemical_formula(
    text: str,
    *,
    source: str | None = None,
    offset: int = 0,
    context: str = "chemical formula",
) -> ChemicalFormula:
    """Parse one compact chemical formula into upright MathML element runs."""
    index = 0
    element_count = 0
    has_subscript = False
    has_group = False
    has_multiletter_element = False
    error_source = source if source is not None else text

    def fail(message: str, position: int) -> FormulaError:
        return FormulaError(
            f"Invalid {context}: {message}",
            position=offset + position,
            expected="chemical element or parenthesized chemical group",
            found=text[position] if position < len(text) else "end of formula",
            source=error_source,
        )

    def parse_sequence(closer: str | None = None) -> etree._Element:
        nonlocal index, element_count, has_subscript, has_group, has_multiletter_element
        children: list[etree._Element] = []

        while index < len(text) and (closer is None or text[index] != closer):
            if text[index] == "(":
                group_start = index
                index += 1
                if index < len(text) and text[index] == ")":
                    raise fail("empty chemical group", group_start)
                inner = parse_sequence(")")
                if index >= len(text) or text[index] != ")":
                    raise fail("missing ')' for chemical group", group_start)
                index += 1
                base = fenced(inner, "()")
                has_group = True
            elif text[index].isupper():
                symbol_match = re.match(r"[A-Z][a-z]?", text[index:])
                assert symbol_match is not None
                symbol = symbol_match.group()
                symbol_start = index
                index += len(symbol)
                if symbol not in CHEMICAL_ELEMENTS:
                    raise fail(f"unknown element symbol {symbol!r}", symbol_start)
                element_count += 1
                has_multiletter_element = has_multiletter_element or len(symbol) == 2
                base = mml("mtext", symbol)
            else:
                raise fail("expected an element symbol", index)

            count_match = re.match(r"[1-9]\d*", text[index:])
            if count_match:
                count = count_match.group()
                index += len(count)
                subscript = mml("msub")
                subscript.extend([base, mml("mn", count)])
                base = subscript
                has_subscript = True
            children.append(base)

        if closer is not None and index >= len(text):
            raise fail(f"missing {closer!r}", max(0, len(text) - 1))
        if not children:
            raise fail("formula is empty", index)
        return mrow(*children)

    if not text:
        raise fail("formula is empty", 0)
    element = parse_sequence()
    if index != len(text):
        raise fail("unexpected trailing text", index)
    return ChemicalFormula(
        element=element,
        element_count=element_count,
        has_subscript=has_subscript,
        has_group=has_group,
        has_multiletter_element=has_multiletter_element,
    )


def _chemical_term_mathml(
    raw: str,
    *,
    source: str,
    offset: int,
    side_name: str,
    term_number: int,
) -> tuple[etree._Element, bool]:
    leading = len(raw) - len(raw.lstrip())
    term = raw.strip()
    term_offset = offset + leading
    if not term:
        raise FormulaError(
            f"Chemical {side_name} term {term_number} is empty",
            position=term_offset,
            expected="chemical formula",
            found="end of side",
            source=source,
        )

    coefficient: str | None = None
    coefficient_match = re.match(r"([1-9]\d*)\s*(?=[A-Z(])", term)
    if coefficient_match:
        coefficient = coefficient_match.group(1)
        consumed = coefficient_match.end()
        term_offset += consumed
        term = term[consumed:]

    state: str | None = None
    state_match = CHEM_STATE_RE.search(term)
    if state_match:
        state = state_match.group(1)
        term = term[: state_match.start()]

    parsed = _parse_chemical_formula(
        term,
        source=source,
        offset=term_offset,
        context=f"chemical formula in {side_name} term {term_number}",
    )
    children: list[etree._Element] = []
    if coefficient is not None:
        children.append(mml("mn", coefficient))
    children.append(parsed.element)
    if state is not None:
        children.append(mml("mtext", f"({state})"))
    distinctive = parsed.distinctive or coefficient is not None or state is not None
    return mrow(*children), distinctive


def _chemical_side_mathml(
    raw: str,
    *,
    source: str,
    offset: int,
    side_name: str,
) -> tuple[etree._Element, bool]:
    segments: list[tuple[int, str]] = []
    depth = 0
    start = 0
    for index, char in enumerate(raw):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "+" and depth == 0:
            segments.append((start, raw[start:index]))
            start = index + 1
    segments.append((start, raw[start:]))

    children: list[etree._Element] = []
    distinctive = len(segments) > 1
    for term_number, (relative_start, segment) in enumerate(segments, start=1):
        term, term_distinctive = _chemical_term_mathml(
            segment,
            source=source,
            offset=offset + relative_start,
            side_name=side_name,
            term_number=term_number,
        )
        if children:
            children.append(mml("mo", "+"))
        children.append(term)
        distinctive = distinctive or term_distinctive
    return mrow(*children), distinctive


def _top_level_chemical_arrows(text: str) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char in "({":
            depth += 1
            index += 1
            continue
        if char in ")}":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0:
            match = CHEM_ARROW_RE.match(text, index)
            if match:
                matches.append(match)
                index = match.end()
                continue
        index += 1
    return matches


def _standalone_chemical_formula(text: str, *, source: str, offset: int) -> ChemicalFormula:
    state_match = CHEM_STATE_RE.search(text)
    formula_text = text[: state_match.start()] if state_match else text
    parsed = _parse_chemical_formula(formula_text, source=source, offset=offset)
    if state_match is not None:
        parsed.element = mrow(parsed.element, mml("mtext", state_match.group()))
    return parsed


def _try_chemistry_mathml(source: str) -> tuple[etree._Element, str, bool] | None:
    """Return chemistry MathML, expression kind, and signal strength when recognized."""
    text = source.strip()
    if not text:
        return None
    source_offset = source.find(text)
    arrows = _top_level_chemical_arrows(text)

    if arrows:
        first_arrow = arrows[0]
        left_result: tuple[etree._Element, bool] | None = None
        right_result: tuple[etree._Element, bool] | None = None
        left_error: FormulaError | None = None
        right_error: FormulaError | None = None
        try:
            left_result = _chemical_side_mathml(
                text[: first_arrow.start()],
                source=source,
                offset=source_offset,
                side_name="reactant",
            )
        except FormulaError as exc:
            left_error = exc
        try:
            right_result = _chemical_side_mathml(
                text[first_arrow.end() :],
                source=source,
                offset=source_offset + first_arrow.end(),
                side_name="product",
            )
        except FormulaError as exc:
            right_error = exc

        distinctive = bool(
            (left_result is not None and left_result[1]) or (right_result is not None and right_result[1])
        )
        if not distinctive:
            return None
        if len(arrows) != 1:
            raise FormulaError(
                "Chemical reaction must contain exactly one top-level arrow",
                position=source_offset + arrows[1].start(),
                expected="one reaction arrow",
                found=arrows[1].group("arrow"),
                source=source,
            )
        if left_error is not None:
            raise left_error
        if right_error is not None:
            raise right_error
        assert left_result is not None and right_result is not None

        arrow = mml("mo", CHEM_ARROW_SYMBOLS[first_arrow.group("arrow")])
        annotation = first_arrow.group("annotation")
        if annotation:
            annotated_arrow = mml("mover")
            annotated_arrow.extend([arrow, mml("mtext", annotation.strip())])
            arrow = annotated_arrow
        chemistry = mrow(left_result[0], arrow, right_result[0])
        root = mml("math", display="inline", nsmap={None: MML_NS})
        root.append(chemistry)
        return root, "reaction", True

    try:
        parsed = _standalone_chemical_formula(text, source=source, offset=source_offset)
    except FormulaError:
        return None
    if not parsed.distinctive:
        return None
    root = mml("math", display="inline", nsmap={None: MML_NS})
    root.append(parsed.element)
    strong = parsed.element_count >= 2 or parsed.has_group
    return root, "formula", strong


def formula_to_mathml(
    source: str,
    aliases: Mapping[str, str] | None = None,
) -> etree._Element:
    if not (aliases and source.strip() in aliases):
        chemistry = _try_chemistry_mathml(source)
        if chemistry is not None:
            return chemistry[0]
    normalized, derivatives = preprocess_formula(source)
    ast = Parser(tokenize(normalized), derivatives, normalized, aliases).parse()
    root = mml("math", display="inline", nsmap={None: MML_NS})
    root.append(node_to_mathml(ast))
    return root


def split_multiline_formula(source: str) -> list[str]:
    """Split reviewed formula text on LaTeX ``\\\\`` or real line breaks."""
    lines = re.split(r"\\\\|\r\n?|\n", source)
    if len(lines) == 1:
        return [source]
    stripped = [line.strip() for line in lines]
    if any(not line for line in stripped):
        raise FormulaError("Multiline formula contains an empty line", source=source)
    return stripped


def find_xsl(explicit: Path | None = None) -> Path:
    if explicit is not None and not explicit.is_file():
        raise FileNotFoundError(f"MML2OMML.XSL was not found at: {explicit}")
    candidates = [
        explicit,
        Path(r"C:\Program Files\Microsoft Office\root\Office16\MML2OMML.XSL"),
        Path(r"C:\Program Files (x86)\Microsoft Office\root\Office16\MML2OMML.XSL"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise FileNotFoundError("MML2OMML.XSL was not found; pass --xsl with its path")


def _mathml_to_omml_xsl(math: etree._Element, transform: etree.XSLT) -> etree._Element:
    """Convert MathML to OMML via Microsoft's MML2OMML.XSL stylesheet."""
    result = transform(etree.ElementTree(math))
    root = result.getroot()
    if root is None:
        raise FormulaError("MML2OMML produced no root element")
    if root.tag == qname(M_NS, "oMathPara"):
        equations = root.xpath(".//m:oMath", namespaces=NS)
        if not equations:
            raise FormulaError("MML2OMML output contains no m:oMath")
        return copy.deepcopy(equations[0])
    if root.tag == qname(M_NS, "oMath"):
        return copy.deepcopy(root)
    equations = root.xpath(".//m:oMath", namespaces=NS)
    if not equations:
        raise FormulaError(f"Unexpected MML2OMML root: {root.tag}")
    return copy.deepcopy(equations[0])


def mathml_to_omml(
    math: etree._Element,
    transform: etree.XSLT | None = None,
) -> etree._Element:
    """Convert MathML to OMML, using XSL when available or the built-in Python backend."""
    if transform is not None:
        omath = _mathml_to_omml_xsl(math, transform)
    else:
        omath = mathml_to_omml_py(math)
    for text_element in omath.xpath(".//m:t", namespaces=NS):
        text = text_element.text or ""
        if text[:1].isspace() or text[-1:].isspace():
            text_element.set(qname(XML_NS, "space"), "preserve")
    return omath


def paragraph_text(paragraph: etree._Element) -> str:
    return "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))


def likely_code(text: str) -> bool:
    stripped = text.strip()
    if CODE_START_RE.search(stripped):
        return True
    if ";" in stripped and re.search(r"\b[A-Za-z_]\w*\s*=", stripped):
        return True
    if re.search(r"\b(?:tf|step|roots|exp)\s*\(", stripped) and stripped.endswith(";"):
        return True
    return False


def math_score(source: str) -> int:
    score = 0
    score += 3 * len(re.findall(r"=|≠|<=|>=|!=|→|⇒|⇌|<->|->|∈|∉|⊂|⊆|⊃|⊇|∝|≡|≅", source))
    score += 2 * len(re.findall(r"[+*/^√±∞→⇒⇌∪∩∧∨⊕⊗]", source))
    score += len(re.findall(r"[A-Za-z]\w*\([^)]*\)", source))
    score += len(re.findall(r"\d", source)) // 2
    if any(
        pattern.search(source) for pattern in (PARTIAL_DERIVATIVE_SCAN_RE, TENSOR_SCAN_RE, BRAKET_SCAN_RE)
    ):
        score += 3
    return score


_STEP_RE = re.compile(r"(?<!\w)(?:1|Γ)\(t\)(?!\w)")


def _looks_like_currency(text: str) -> bool:
    return bool(re.fullmatch(r"\s*\d+(?:[.,]\d{2})?\s*", text))


def _latex_delimited_spans(text: str) -> list[CandidateSpan]:
    spans: list[CandidateSpan] = []
    claimed: list[tuple[int, int]] = []
    index = 0

    while index < len(text):
        if text.startswith("$$", index):
            end = text.find("$$", index + 2)
            if end == -1:
                index += 2
                continue
            span_end = end + 2
            inner = text[index + 2 : end].strip()
            if inner:
                spans.append(CandidateSpan(index, span_end, text[index:span_end], inner, True, True))
                claimed.append((index, span_end))
            index = span_end
            continue

        if text[index] == "$" and not any(start <= index < end for start, end in claimed):
            if index + 1 < len(text) and text[index + 1] == "$":
                index += 1
                continue
            end = text.find("$", index + 1)
            if end == -1:
                index += 1
                continue
            span_end = end + 1
            inner = text[index + 1 : end].strip()
            if inner and not _looks_like_currency(inner):
                spans.append(CandidateSpan(index, span_end, text[index:span_end], inner, False, True))
                claimed.append((index, span_end))
            index = span_end
            continue

        index += 1

    return spans


def _range_overlaps(start: int, end: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(start < claimed_end and end > claimed_start for claimed_start, claimed_end in ranges)


def _chemistry_spans(text: str, claimed: Sequence[tuple[int, int]]) -> list[CandidateSpan]:
    """Find conservative standalone chemistry and full-reaction spans."""
    spans: list[CandidateSpan] = []
    reaction_ranges: list[tuple[int, int]] = []

    for match in CHEM_REACTION_SCAN_RE.finditer(text):
        start, end = match.span("reaction")
        if _range_overlaps(start, end, claimed):
            continue
        source = match.group("reaction")
        try:
            chemistry = _try_chemistry_mathml(source)
        except FormulaError:
            continue
        if chemistry is None or chemistry[1] != "reaction":
            continue
        spans.append(CandidateSpan(start, end, source, chemistry=True))
        reaction_ranges.append((start, end))

    occupied = [*claimed, *reaction_ranges]
    for match in CHEM_FORMULA_SCAN_RE.finditer(text):
        start, end = match.span("formula")
        if _range_overlaps(start, end, occupied):
            continue
        source = match.group("formula")
        try:
            chemistry = _try_chemistry_mathml(source)
        except FormulaError:
            continue
        if chemistry is None or chemistry[1] != "formula":
            continue
        # Single elemental symbols are too ambiguous for automatic prose scanning.
        if not chemistry[2] and not re.search(r"\d|\((?:aq|g|l|s)\)$", source):
            continue
        spans.append(CandidateSpan(start, end, source, chemistry=True))

    return spans


def _physics_spans(text: str, claimed: Sequence[tuple[int, int]]) -> list[CandidateSpan]:
    """Find supported physics notation without promoting ambiguous prose to high confidence."""
    spans: list[CandidateSpan] = []
    occupied = list(claimed)
    patterns = (
        (PARTIAL_DERIVATIVE_SCAN_RE, "partial_derivative"),
        (TENSOR_SCAN_RE, "tensor"),
        (BRAKET_SCAN_RE, "braket"),
    )
    for pattern, kind in patterns:
        for match in pattern.finditer(text):
            start, end = match.span()
            if _range_overlaps(start, end, occupied):
                continue
            source = match.group()
            try:
                formula_to_mathml(source)
            except FormulaError:
                continue
            spans.append(CandidateSpan(start, end, source, physics=kind))
            occupied.append((start, end))
    return spans


def _physics_kind(source: str) -> str | None:
    for pattern, kind in (
        (PARTIAL_DERIVATIVE_SCAN_RE, "partial_derivative"),
        (TENSOR_SCAN_RE, "tensor"),
        (BRAKET_SCAN_RE, "braket"),
    ):
        if pattern.search(source):
            return kind
    return None


def candidate_spans(
    text: str,
    recognizers: Sequence[FormulaRecognizer] = (),
) -> list[CandidateSpan]:
    """Find built-in and opt-in plugin candidates in one paragraph.

    Built-in spans take precedence over plugin spans.  Plugins are evaluated in
    the order provided, with the first non-overlapping result winning.
    """
    candidates: list[CandidateSpan] = []

    latex_spans = _latex_delimited_spans(text)
    candidates.extend(latex_spans)
    latex_ranges = [(span.start, span.end) for span in latex_spans]

    # Detect step function 1(t) / Γ(t) with exact pattern before general scan
    step_spans: set[tuple[int, int]] = set()
    for match in _STEP_RE.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in latex_ranges):
            continue
        step_spans.add((match.start(), match.end()))
        candidates.append(CandidateSpan(match.start(), match.end(), match.group()))

    claimed_ranges = [*latex_ranges, *step_spans]
    chemistry_spans = _chemistry_spans(text, claimed_ranges)
    candidates.extend(chemistry_spans)
    chemistry_ranges = [(span.start, span.end) for span in chemistry_spans]
    claimed_ranges.extend(chemistry_ranges)

    index = 0
    while index < len(text):
        # Skip spans already claimed by an exact or explicit detector.
        while any(s <= index < e for s, e in claimed_ranges):
            index = next(e for s, e in claimed_ranges if s <= index < e)
        if index >= len(text):
            break
        if text[index] not in MATH_CHARS:
            index += 1
            continue
        start = index
        while index < len(text) and text[index] in MATH_CHARS:
            index += 1
        end = index
        raw = text[start:end]
        left_trim = len(raw) - len(raw.lstrip(TRIM_PUNCT))
        right_trim = len(raw) - len(raw.rstrip(TRIM_PUNCT))
        start += left_trim
        end -= right_trim
        source = text[start:end]
        if not source or not FORMULA_ANCHOR_RE.search(source) or math_score(source) < 4:
            continue
        source = re.split(r"\.\s+(?=[A-Za-z])", source, maxsplit=1)[0]
        source = re.split(r",?\s+(?:avec|si|et|Elle|La|Pour)\b", source, maxsplit=1, flags=re.IGNORECASE)[0]
        source = re.sub(
            r"^.*\b(?:est|sont|vaut|discriminant|vers|equals?|is)\s+",
            "",
            source,
            flags=re.IGNORECASE,
        )
        source = source.strip(TRIM_PUNCT)
        if not source or not FORMULA_ANCHOR_RE.search(source) or math_score(source) < 4:
            continue
        start = text.find(source, start, end)
        end = start + len(source)
        if source and start >= 0:
            candidates.append(CandidateSpan(start, end, source))

    # Let complete anchored equations claim their ranges before adding
    # standalone physics notation such as ``T_i^j`` or ``<phi|psi>``.
    occupied_ranges = [(span.start, span.end) for span in candidates]
    candidates.extend(_physics_spans(text, occupied_ranges))
    deduped: list[CandidateSpan] = []
    for item in sorted(candidates, key=lambda span: (span.start, span.end)):
        if not deduped or (item.start, item.end) != (deduped[-1].start, deduped[-1].end):
            deduped.append(item)
    plugin_spans = recognize_with_plugins(
        text,
        recognizers,
        claimed=[(span.start, span.end) for span in deduped],
    )
    return sorted([*deduped, *plugin_spans], key=lambda span: (span.start, span.end))


def candidate_runs(
    text: str,
    recognizers: Sequence[FormulaRecognizer] = (),
) -> list[tuple[int, int, str]]:
    return [(span.start, span.end, span.source) for span in candidate_spans(text, recognizers)]


def scan_docx(
    input_path: Path,
    report_path: Path,
    alias_profile: AliasProfile | None = None,
    *,
    recognizers: Sequence[FormulaRecognizer] = (),
) -> dict[str, object]:
    if input_path.suffix.lower() != ".docx":
        raise ValueError("Input must be a .docx file")
    if not input_path.is_file():
        raise FileNotFoundError(f"Input DOCX was not found: {input_path}")
    active_recognizers = normalize_recognizers(recognizers)
    _, parts = inspect_docx(input_path)
    report: dict[str, object] = {
        "schema_version": 2,
        "input": str(input_path.resolve()),
        "profile": {
            "derivatives": "fraction",
            "unit_step": "u(t)",
            "output": "native_word_omml",
            "aliases": alias_profile_metadata(alias_profile),
            "recognizers": recognizers_metadata(active_recognizers),
        },
        "summary": {
            "paragraphs": 0,
            "candidates": 0,
            "existing_equations": 0,
            "drawing_paragraphs": 0,
            "code_paragraphs": 0,
        },
        "candidates": [],
    }
    candidates: list[dict[str, object]] = []
    summary = report["summary"]
    assert isinstance(summary, dict)

    for part_name, raw in parts.items():
        if not TARGET_PART_RE.match(part_name):
            continue
        root = parse_xml_part(raw, part_name=part_name)
        paragraphs = root.xpath(".//w:p", namespaces=NS)
        for paragraph_index, paragraph in enumerate(paragraphs):
            summary["paragraphs"] += 1
            if paragraph.xpath(".//m:oMath | .//m:oMathPara", namespaces=NS):
                summary["existing_equations"] += 1
                continue
            if paragraph.xpath(".//w:drawing | .//w:pict", namespaces=NS):
                summary["drawing_paragraphs"] += 1
                continue
            text = paragraph_text(paragraph)
            if not text.strip():
                continue
            if likely_code(text):
                scan_spans = _latex_delimited_spans(text)
                scan_spans.extend(
                    recognize_with_plugins(
                        text,
                        active_recognizers,
                        claimed=[(span.start, span.end) for span in scan_spans],
                    )
                )
                scan_spans.sort(key=lambda span: (span.start, span.end))
                if not scan_spans:
                    summary["code_paragraphs"] += 1
                    continue
            else:
                scan_spans = candidate_spans(text, active_recognizers)
            for span in scan_spans:
                candidate_id = f"f{len(candidates) + 1:04d}"
                start, end, source = span.start, span.end, span.source
                linear = span.linear or source
                display = span.display or text.strip() == source.strip()
                score = math_score(linear)
                has_relation = bool(re.search(r"[=≠≤≥≈≅→⇒⇌∈∉⊂⊆⊃⊇∝≡]|<->|->", linear))
                has_func = bool(re.search(r"\([^)]*\)", linear))
                chemistry_kind: str | None = None
                chemistry_strong = False
                physics_kind = span.physics or _physics_kind(linear)
                try:
                    chemistry = _try_chemistry_mathml(linear)
                    if chemistry is not None:
                        chemistry_kind = chemistry[1]
                        chemistry_strong = chemistry[2]
                except FormulaError:
                    chemistry = None
                if span.recognizer is not None:
                    confidence = span.confidence or "medium"
                    reason = span.confidence_reason or f"custom recognizer {span.recognizer!r}"
                elif span.explicit:
                    confidence = "high"
                    reason = "explicit LaTeX delimiter"
                elif chemistry_kind == "reaction":
                    confidence = "high"
                    reason = "chemical reaction pattern"
                elif chemistry_kind == "formula" and chemistry_strong:
                    confidence = "high"
                    reason = "distinctive chemical formula pattern"
                elif chemistry_kind == "formula":
                    confidence = "medium"
                    reason = "ambiguous single-element chemical formula; review required"
                elif physics_kind == "partial_derivative" and "∂" in linear:
                    confidence = "high"
                    reason = "distinctive Unicode partial derivative pattern"
                elif physics_kind is not None:
                    confidence = "medium"
                    reason = f"physics {physics_kind} pattern; review required"
                elif score >= 8 and has_relation:
                    confidence = "high"
                    reason = "strong formula signal"
                elif score >= 6 or (score >= 4 and (has_relation or has_func)):
                    confidence = "medium"
                    reason = "moderate formula signal"
                else:
                    confidence = "low"
                    reason = "weak formula signal; likely prose"

                candidate = {
                    "id": candidate_id,
                    "selected": confidence == "high",
                    "part": part_name,
                    "paragraph_index": paragraph_index,
                    "start": start,
                    "end": end,
                    "source": source,
                    "linear": linear,
                    "display": display,
                    "paragraph_text": text,
                    "confidence": confidence,
                    "confidence_reason": reason,
                    "explicit": span.explicit,
                    "chemistry": chemistry_kind is not None,
                    "chemistry_kind": chemistry_kind,
                    "physics": physics_kind is not None,
                    "physics_kind": physics_kind,
                    "recognizer": span.recognizer,
                    "recognizer_kind": span.kind,
                }
                try:
                    formula_lines = split_multiline_formula(linear)
                    for formula_line in formula_lines:
                        formula_to_mathml(
                            formula_line,
                            aliases=alias_profile.aliases if alias_profile is not None else None,
                        )
                    candidate["multiline"] = len(formula_lines) > 1
                    candidate["line_count"] = len(formula_lines)
                    candidate["parse_status"] = "ok"
                except Exception as exc:
                    candidate["selected"] = False
                    candidate["parse_status"] = "review"
                    candidate["parse_error"] = str(exc)
                    candidate["parse_error_details"] = _error_details(exc)
                candidates.append(candidate)
    summary["candidates"] = len(candidates)
    report["candidates"] = candidates
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def ancestor_run(text_node: etree._Element, paragraph: etree._Element) -> etree._Element | None:
    current = text_node.getparent()
    while current is not None and current is not paragraph:
        if current.tag == qname(W_NS, "r") and current.getparent() is paragraph:
            return current
        current = current.getparent()
    return None


def _preserve_boundary_spaces(text_element: etree._Element) -> None:
    value = text_element.text or ""
    if value.startswith(" ") or value.endswith(" "):
        text_element.set(qname(XML_NS, "space"), "preserve")


def run_with_text_like(run: etree._Element, text: str) -> etree._Element:
    new_run = etree.Element(qname(W_NS, "r"))
    rpr = run.find(qname(W_NS, "rPr"))
    if rpr is not None:
        new_run.append(copy.deepcopy(rpr))
    text_element = etree.SubElement(new_run, qname(W_NS, "t"))
    if text.startswith(" ") or text.endswith(" "):
        text_element.set(qname(XML_NS, "space"), "preserve")
    text_element.text = text
    return new_run


def replace_inline_span(paragraph: etree._Element, start: int, end: int, omath: etree._Element) -> None:
    text_nodes = paragraph.xpath(".//w:t", namespaces=NS)
    offsets: list[tuple[etree._Element, int, int]] = []
    cursor = 0
    for node in text_nodes:
        value = node.text or ""
        offsets.append((node, cursor, cursor + len(value)))
        cursor += len(value)
    touched = [(node, lo, hi) for node, lo, hi in offsets if hi > start and lo < end]
    if not touched:
        raise FormulaError("Candidate span does not overlap any text node")
    start_node, start_lo, _ = touched[0]
    end_node, end_lo, _ = touched[-1]
    start_run = ancestor_run(start_node, paragraph)
    end_run = ancestor_run(end_node, paragraph)
    if start_run is None or end_run is None:
        raise FormulaError("Formula span crosses a hyperlink or unsupported nested run")

    start_value = start_node.text or ""
    end_value = end_node.text or ""
    prefix = start_value[: max(0, start - start_lo)]
    suffix = end_value[max(0, end - end_lo) :]

    for node, lo, hi in touched:
        value = node.text or ""
        keep_left = value[: max(0, start - lo)] if node is start_node else ""
        keep_right = value[max(0, end - lo) :] if node is end_node else ""
        node.text = keep_left + keep_right
        _preserve_boundary_spaces(node)
    start_node.text = prefix
    _preserve_boundary_spaces(start_node)

    parent = paragraph
    insert_index = parent.index(start_run) + 1
    parent.insert(insert_index, omath)
    if start_run is end_run and suffix:
        start_node.text = prefix
        parent.insert(insert_index + 1, run_with_text_like(start_run, suffix))


def replace_display_paragraph(paragraph: etree._Element, omath: etree._Element) -> None:
    for child in list(paragraph):
        if child.tag != qname(W_NS, "pPr"):
            paragraph.remove(child)
    math_para = etree.Element(qname(M_NS, "oMathPara"))
    math_para.append(omath)
    paragraph.append(math_para)


def replace_multiline_table_formula(
    paragraph: etree._Element,
    equations: Sequence[etree._Element],
    suffix: str = "",
) -> None:
    for child in list(paragraph):
        if child.tag != qname(W_NS, "pPr"):
            paragraph.remove(child)
    for index, equation in enumerate(equations):
        if index:
            run = etree.SubElement(paragraph, qname(W_NS, "r"))
            etree.SubElement(run, qname(W_NS, "br"))
        paragraph.append(equation)
    if suffix:
        run = etree.SubElement(paragraph, qname(W_NS, "r"))
        text = etree.SubElement(run, qname(W_NS, "t"))
        text.text = suffix


def split_top_level_additive(text: str, target_length: int = 30) -> list[str]:
    depth = 0
    starts = [0]
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and char in "+-" and index > 0:
            previous = text[index - 1]
            if previous not in "=<>+-*/^(,":
                starts.append(index)
    if len(starts) == 1:
        return [text]
    terms = [
        text[starts[i] : starts[i + 1] if i + 1 < len(starts) else len(text)] for i in range(len(starts))
    ]
    lines: list[str] = []
    current = ""
    for term in terms:
        if current and len(current) + len(term) > target_length:
            lines.append(current)
            current = term
        else:
            current += term
    if current:
        lines.append(current)
    return lines


def estimated_formula_width(text: str) -> int:
    derivative_count = len(re.findall(r"(?:''|'|¨|˙)\s*\(", text))
    return len(text) + derivative_count * 18


def _path_value(path: Path | None) -> str | None:
    return str(path.resolve()) if path is not None else None


def _candidate_location(candidate: dict[str, object]) -> dict[str, object]:
    return {
        "part": candidate.get("part"),
        "paragraph_index": candidate.get("paragraph_index"),
        "start": candidate.get("start"),
        "end": candidate.get("end"),
    }


def _error_details(exc: Exception) -> dict[str, object]:
    if isinstance(exc, FormulaError):
        return exc.to_dict()
    return {"message": str(exc)}


def _formula_report_item(
    candidate: dict[str, object],
    *,
    status: str,
    message: str | None = None,
    lines: int | None = None,
    layout: str | None = None,
    error_details: dict[str, object] | None = None,
    warning_code: str | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "id": candidate.get("id"),
        "status": status,
        "source": candidate.get("source"),
        "linear": candidate.get("linear", candidate.get("source")),
        "confidence": candidate.get("confidence"),
        "display": bool(candidate.get("display")),
        "location": _candidate_location(candidate),
        "recognizer": candidate.get("recognizer"),
        "recognizer_kind": candidate.get("recognizer_kind"),
    }
    if lines is not None:
        item["lines"] = lines
        item["multiline"] = lines > 1
    if layout is not None:
        item["layout"] = layout
    if message:
        key = "error" if status in {"failed", "skipped"} else "message"
        item[key] = message
    if error_details:
        item["error_details"] = error_details
    if warning_code and message:
        item["warnings"] = [{"code": warning_code, "message": message}]
    return item


def _conversion_report(
    *,
    command_name: str,
    input_path: Path,
    review_path: Path,
    output_path: Path,
    result_path: Path,
    xsl_path: Path | None,
    selected_count: int,
    dry_run: bool,
    strict: bool,
    alias_profile: AliasProfile | None,
    recognizers: list[dict[str, object]],
) -> dict[str, object]:
    backend = "office-xsl" if xsl_path is not None else "python"
    return {
        "schema_version": 3,
        "report_type": "conversion",
        "mathfmt": __version__,
        "command": {"name": command_name},
        "inputs": {
            "docx": _path_value(input_path),
            "review": _path_value(review_path),
            "aliases": _path_value(alias_profile.path) if alias_profile is not None else None,
        },
        "outputs": {
            "docx": _path_value(output_path),
            "report": _path_value(result_path),
        },
        "options": {
            "backend": backend,
            "xsl": _path_value(xsl_path),
            "dry_run": dry_run,
            "strict": strict,
            "alias_profile": alias_profile_metadata(alias_profile),
            "recognizers": recognizers,
        },
        "summary": {
            "selected": selected_count,
            "converted": 0,
            "skipped": 0,
            "failed": 0,
            "warnings": 0,
            "dry_run": dry_run,
            "output_written": False,
            "strict_failed": False,
        },
        "formulas": [],
        # Backwards-compatible v0.2.x fields:
        "input": _path_value(input_path),
        "output": _path_value(output_path),
        "review": _path_value(review_path),
        "xsl": _path_value(xsl_path),
        "converted": [],
        "skipped": [],
    }


def set_math_font_size(omath: etree._Element, half_points: int) -> None:
    for math_run in omath.xpath(".//m:r", namespaces=NS):
        word_rpr = math_run.find(qname(W_NS, "rPr"))
        if word_rpr is None:
            word_rpr = etree.Element(qname(W_NS, "rPr"))
            math_rpr = math_run.find(qname(M_NS, "rPr"))
            insert_at = 1 if math_rpr is not None else 0
            math_run.insert(insert_at, word_rpr)
        for local in ("sz", "szCs"):
            size = word_rpr.find(qname(W_NS, local))
            if size is None:
                size = etree.SubElement(word_rpr, qname(W_NS, local))
            size.set(qname(W_NS, "val"), str(half_points))


def apply_docx(
    input_path: Path,
    review_path: Path,
    output_path: Path,
    result_path: Path,
    xsl_path: Path | None = None,
    *,
    command_name: str = "apply",
    dry_run: bool = False,
    strict: bool = False,
    alias_profile: AliasProfile | None = None,
) -> dict[str, object]:
    if input_path.suffix.lower() != ".docx" or output_path.suffix.lower() != ".docx":
        raise ValueError("Input and output must be .docx files")
    if not dry_run and input_path.resolve() == output_path.resolve():
        raise ValueError("Refusing to overwrite the input DOCX")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    validate_review_alias_profile(review, alias_profile)
    review_profile = review.get("profile")
    review_recognizers = review_profile.get("recognizers", []) if isinstance(review_profile, dict) else []
    if not isinstance(review_recognizers, list) or not all(
        isinstance(item, dict) for item in review_recognizers
    ):
        raise ValueError("Review report contains invalid recognizer metadata")
    candidates = [c for c in review.get("candidates", []) if c.get("selected")]
    infos, parts = inspect_docx(input_path)
    transform = etree.XSLT(etree.parse(str(xsl_path))) if xsl_path is not None else None
    result = _conversion_report(
        command_name=command_name,
        input_path=input_path,
        review_path=review_path,
        output_path=output_path,
        result_path=result_path,
        xsl_path=xsl_path,
        selected_count=len(candidates),
        dry_run=dry_run,
        strict=strict,
        alias_profile=alias_profile,
        recognizers=review_recognizers,
    )
    converted = result["converted"]
    skipped = result["skipped"]
    formulas = result["formulas"]
    assert isinstance(converted, list)
    assert isinstance(skipped, list)
    assert isinstance(formulas, list)

    grouped: dict[str, dict[int, list[dict[str, object]]]] = {}
    for candidate in candidates:
        part_name = str(candidate["part"])
        paragraph_index = int(candidate["paragraph_index"])
        grouped.setdefault(part_name, {}).setdefault(paragraph_index, []).append(candidate)

    for part_name, paragraph_groups in grouped.items():
        if part_name not in parts:
            for group in paragraph_groups.values():
                for candidate in group:
                    error = "DOCX part not found"
                    skipped.append({"id": candidate.get("id"), "error": error})
                    formulas.append(
                        _formula_report_item(
                            candidate,
                            status="skipped",
                            message=error,
                            warning_code="location_skipped",
                        )
                    )
            continue
        root = parse_xml_part(parts[part_name], part_name=part_name)
        paragraphs = root.xpath(".//w:p", namespaces=NS)
        for paragraph_index, group in paragraph_groups.items():
            if not 0 <= paragraph_index < len(paragraphs):
                for candidate in group:
                    error = "Paragraph index out of range"
                    skipped.append({"id": candidate.get("id"), "error": error})
                    formulas.append(
                        _formula_report_item(
                            candidate,
                            status="skipped",
                            message=error,
                            warning_code="location_skipped",
                        )
                    )
                continue
            paragraph = paragraphs[paragraph_index]
            original_text = paragraph_text(paragraph)
            for candidate in sorted(group, key=lambda c: int(c["start"]), reverse=True):
                try:
                    start, end = int(candidate["start"]), int(candidate["end"])
                    source = str(candidate["source"])
                    if original_text[start:end] != source:
                        raise FormulaError("Reviewed source no longer matches the paragraph span")
                    linear = str(candidate.get("linear", source))
                    in_table = bool(paragraph.xpath("ancestor::w:tc", namespaces=NS))
                    is_display = bool(candidate.get("display")) and source.strip() == original_text.strip()
                    outside_formula = original_text[:start] + original_text[end:]
                    covers_formula_paragraph = not outside_formula.strip(TRIM_PUNCT)
                    reviewed_lines = split_multiline_formula(linear)
                    explicit_multiline = len(reviewed_lines) > 1
                    table_lines = reviewed_lines
                    if (
                        not explicit_multiline
                        and in_table
                        and covers_formula_paragraph
                        and estimated_formula_width(linear) > 65
                    ):
                        table_lines = split_top_level_additive(linear)
                    line_equations = [
                        mathml_to_omml(
                            formula_to_mathml(
                                line,
                                aliases=alias_profile.aliases if alias_profile is not None else None,
                            ),
                            transform,
                        )
                        for line in table_lines
                    ]
                    if explicit_multiline:
                        equations = [combine_equation_array(line_equations)]
                        layout = "equation_array"
                    else:
                        equations = line_equations
                        layout = "line_breaks" if len(equations) > 1 else "single"
                    if in_table:
                        for equation in equations:
                            set_math_font_size(equation, 16)
                    if explicit_multiline and is_display:
                        replace_display_paragraph(paragraph, equations[0])
                    elif explicit_multiline:
                        replace_inline_span(paragraph, start, end, equations[0])
                    elif len(equations) > 1:
                        replace_multiline_table_formula(paragraph, equations, original_text[end:])
                    elif is_display:
                        omath = equations[0]
                        replace_display_paragraph(paragraph, omath)
                    else:
                        omath = equations[0]
                        replace_inline_span(paragraph, start, end, omath)
                    line_count = len(table_lines)
                    converted.append(
                        {
                            "id": candidate.get("id"),
                            "source": source,
                            "part": part_name,
                            "lines": line_count,
                            "layout": layout,
                        }
                    )
                    formulas.append(
                        _formula_report_item(
                            candidate,
                            status="converted",
                            lines=line_count,
                            layout=layout,
                        )
                    )
                except Exception as exc:
                    error = str(exc)
                    skipped.append(
                        {"id": candidate.get("id"), "source": candidate.get("source"), "error": error}
                    )
                    formulas.append(
                        _formula_report_item(
                            candidate,
                            status="failed",
                            message=error,
                            error_details=_error_details(exc),
                            warning_code="conversion_failed",
                        )
                    )
        parts[part_name] = etree.tostring(
            root,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )

    output_written = False
    strict_failed = strict and bool(skipped)
    if not dry_run and not strict_failed:
        write_docx(output_path, infos, parts)
        output_written = True
    result["converted_count"] = len(converted)
    result["skipped_count"] = len(skipped)
    summary = result["summary"]
    assert isinstance(summary, dict)
    summary["converted"] = len(converted)
    summary["skipped"] = len(skipped)
    summary["failed"] = sum(1 for item in formulas if item.get("status") == "failed")
    summary["warnings"] = sum(1 for item in formulas if item.get("warnings"))
    summary["output_written"] = output_written
    summary["strict_failed"] = strict_failed
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
