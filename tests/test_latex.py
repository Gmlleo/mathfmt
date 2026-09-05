from __future__ import annotations

import pytest

from mathfmt.core import FormulaError
from mathfmt.latex import KNOWN_MACROS, contains_latex_macro, expand_latex


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\alpha + \beta", "α + β"),
        (r"\Gamma \Omega", "Γ Ω"),
        (r"a \leq b", "a ≤ b"),
        (r"a \neq b", "a ≠ b"),
        (r"a \pm b", "a ± b"),
        (r"a \mp b", "a ∓ b"),
        (r"a \times b \cdot c \div d", "a × b · c ÷ d"),
        (r"x \to y", "x → y"),
        (r"x \Rightarrow y", "x ⇒ y"),
        (r"x \in A \cup B", "x ∈ A ∪ B"),
        (r"\infty", "∞"),
        (r"\nabla f", "∇ f"),
        (r"\sin x + \cos y", "sin x + cos y"),
        (r"a \, b \quad c", "a  b  c"),
    ],
)
def test_symbol_macros_expand(source: str, expected: str) -> None:
    assert expand_latex(source).split() == expected.split()


def test_expansion_leaves_non_macro_text_untouched() -> None:
    # The expander is a text-to-text pass, not a parser: everything between
    # macros — including the structural characters MathFmt's own syntax uses —
    # reaches the tokenizer exactly as written.
    assert expand_latex(r"f(x)^2 \leq \alpha_1") == "f(x)^2 ≤ α_1"


@pytest.mark.parametrize("text", [r"\alpha", r"x \, y", r"\sin x", r"a \leq b"])
def test_contains_latex_macro_detects_macros(text: str) -> None:
    assert contains_latex_macro(text) is True


@pytest.mark.parametrize("text", ["x^2 + 1", "H2O", r"C:\Users\gml85", "a = b", "sqrt(x)"])
def test_contains_latex_macro_ignores_non_macros(text: str) -> None:
    # `C:\Users\gml85` is the load-bearing one: \Users is not a macro this
    # module knows, so a Windows path is never mistaken for LaTeX. That is what
    # keeps paths out of the scanner's bare-macro detector.
    assert contains_latex_macro(text) is False


@pytest.mark.parametrize("source", [r"\substack{a}", r"\mathcal{L}", r"\overbrace{x}", r"\newcommand"])
def test_unsupported_macro_is_rejected_with_a_hint(source: str) -> None:
    with pytest.raises(FormulaError) as excinfo:
        expand_latex(source)
    details = excinfo.value.to_dict()
    assert details["hint"]
    assert source.split("{")[0] in str(excinfo.value)


@pytest.mark.parametrize("name", sorted(KNOWN_MACROS))
def test_detection_and_expansion_agree_on_every_known_macro(name: str) -> None:
    # The invariant that keeps the scanner honest: contains_latex_macro is what
    # promotes a span to a candidate, and expand_latex is what that candidate
    # is then parsed through. A name known to one but not the other would make
    # the scanner report a formula that can never convert — so both directions
    # read one set, and this pins that they stay in step as later tasks add
    # argument-taking macros.
    assert contains_latex_macro("\\" + name) is True
    try:
        expand_latex("\\" + name)
    except FormulaError as error:
        # A macro may still complain about *missing arguments* — a different,
        # legitimate error. It must never claim to be unsupported.
        assert "does not support" not in str(error)
