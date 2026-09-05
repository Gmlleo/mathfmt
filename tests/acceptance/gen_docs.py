"""Generate acceptance-test DOCX files with real-world formulas."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

OUT = Path(__file__).resolve().parent

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def _wrap_body(content: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <w:body>
  {content}
  <w:sectPr>
   <w:pgSz w:w="11906" w:h="16838"/>
   <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720"/>
  </w:sectPr>
 </w:body>
</w:document>"""


def _p(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r></w:p>'


def _write(name: str, paragraphs: list[str]) -> Path:
    path = OUT / name
    body = "\n".join(_p(p) for p in paragraphs)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/document.xml", _wrap_body(body))
    return path


def doc01_basic() -> Path:
    """Basic arithmetic, subscripts, superscripts, radicals, fractions."""
    return _write(
        "doc01_basic.docx",
        [
            "Simple superscript: E = m c^2 is famous.",
            "Subscript: The sequence a1, a2, ..., an converges.",
            "Combined: x_1^2 + x_2^2 = r^2.",
            "Square root: sqrt(x^2 + y^2) gives the distance.",
            "Cube root: The solution is root3(27) = 3.",
            "Fraction: The ratio is a/(b+c), not a/b+c.",
            "Inequality: x != 0 and x >= 3.",
            "Sum formula: 1 + 2 + ... + n = n(n+1)/2.",
        ],
    )


def doc02_advanced() -> Path:
    """Derivatives, integrals, limits, Greek letters, trig."""
    return _write(
        "doc02_advanced.docx",
        [
            "First derivative: ds(t)/dt = v(t).",
            "Second derivative: d^2s(t)/dt^2 = a(t).",
            "Partial derivative: df/dx and df/dy.",
            "Definite integral: int(0, pi) sin(x) dx = 2.",
            "Indefinite integral: int(cos(x)) dx = sin(x) + C.",
            "Limit: lim(x->0) sin(x)/x = 1.",
            "Limit to infinity: lim(n->oo) (1+1/n)^n = e.",
            "Sum notation: sum(k=1, n) k = n(n+1)/2.",
            "Product notation: prod(i=1, n) i = n!.",
            "Greek: Alpha + beta = gamma, Delta x -> 0.",
            "Trig: sin(x) + cos(x) = sqrt(2) sin(x + pi/4).",
            "Exponential: e^(p1*t) decays when p1 < 0.",
        ],
    )


def doc03_mixed() -> Path:
    """Formulas embedded in paragraphs with Chinese text and tables."""
    return _write(
        "doc03_mixed.docx",
        [
            "一元二次方程 x^2 + bx + c = 0 的求根公式为 x = (-b +- sqrt(b^2 - 4ac)) / (2a)。",
            "求导法则：ds(t)/dt 表示位移对时间的导数，即速度。",
            "极限定义：lim(x->0) f(x) = L 表示当 x 趋近于 0 时 f(x) 的极限为 L。",
            "积分计算：int(0, T) v(t) dt 给出时间段 [0, T] 内的位移。",
            "常见不等式：对于任意实数 x，有 x^2 >= 0，且 sqrt(x^2) = |x|。",
            "概率公式：P(A|B) = P(A and B) / P(B)，其中 P(B) != 0。",
            "This is a mixed paragraph: x^2 + y^2 = r^2 描述圆方程。",
            "The derivative ds(t)/dt is velocity, and d^2s(t)/dt^2 is acceleration.",
        ],
    )


def doc04_edge_cases() -> Path:
    """Edge cases: empty, near-empty, long formula, Unicode, tables."""
    return _write(
        "doc04_edge_cases.docx",
        [
            "Very long: x^1+x^2+x^3+x^4+x^5+x^6+x^7+x^8+x^9+x^10 = 0.",
            "",  # empty paragraph
            "   ",  # whitespace only
            "No formula here, just plain English text.",
            "Unicode: α + β = γ and Δ ≠ ∇.",
            "Complex fraction: (a+b)/(c+d) + e/(f+g).",
            "Nested: sqrt(a + sqrt(b + sqrt(c))).",
            "Brackets: {[(1+2)*3]^2} / 5.",
            "Underscore in text: file_name and var_name are identifiers.",
            "Comparison operators: x <= y, x >= y, x != y, x == y.",
            "Step function: 1(t) is the unit step, not the number one.",
            "Special: d/dt 不是除法，而是微分算子。",
        ],
    )


def doc05_textbook() -> Path:
    """Realistic textbook excerpt — calculus problems."""
    return _write(
        "doc05_textbook.docx",
        [
            "Calculus Practice Problems",
            "",
            "1. Find the derivative of f(x) = x^3 + 2x^2 - 5x + 7.",
            "   Answer: f'(x) = 3x^2 + 4x - 5.",
            "",
            "2. Evaluate the limit: lim(x->0) (sin(3x))/x.",
            "   Hint: Use lim(x->0) sin(x)/x = 1.",
            "   Answer: 3.",
            "",
            "3. Compute the definite integral: int(0, 1) x^2 dx.",
            "   Answer: 1/3.",
            "",
            "4. Solve: d^2y(t)/dt^2 + 4 y(t) = 0 with y(0)=1, dy(0)/dt=0.",
            "   Answer: y(t) = cos(2t).",
            "",
            "5. Evaluate sum(k=1, n) (2k - 1).",
            "   Answer: n^2.",
            "",
            "6. Find the area between y = x^2 and y = x^3 from x = 0 to x = 1.",
            "   Answer: 1/12.",
            "",
            "7. Taylor series: e^x = sum(n=0, oo) x^n / n!.",
            "   For small x, e^x ≈ 1 + x + x^2/2 + x^3/6.",
            "",
            "8. Standard deviation: s = sqrt((1/(n-1)) sum(i=1, n) (x_i - x_bar)^2).",
        ],
    )


def doc06_v040() -> Path:
    """v0.4 notation: explicit, multiline, cases, chemistry, physics, and Unicode."""
    return _write(
        "doc06_v040.docx",
        [
            "MathFmt v0.4 Visual Acceptance",
            "",
            "$x ∈ ℝ$",
            "$A ⊆ B$",
            "$A ∪ B$",
            "$u ⊗ v$",
            "$f(x) = {0, x<0; 1, x>=0}$",
            r"$$a = b \\ c = d$$",
            "$2H2 + O2 ->[heat] 2H2O$",
            "$∂f/∂x = 2x$",
            "$<phi|psi> = 0$",
            "${a+b}/c$",
        ],
    )


def doc07_latex() -> Path:
    """v1.3 notation: LaTeX delimiters, bare macros, accents, and environments."""
    return _write(
        "doc07_latex.docx",
        [
            "MathFmt v1.3 LaTeX Acceptance",
            "",
            r"由此可得 \(\frac{a}{b}\) 成立。",
            r"体积公式为 \[ V = \sqrt[3]{x} \]",
            r"样本均值记为 \bar{x}。",
            r"求和式 \sum_{i=1}^{n} i 收敛。",
            # Wrapped in $…$ because the row separator is only meaningful once
            # the environment around it is gone: as an explicit span this stays
            # one candidate and exercises the delimiter path as well.
            r"$\begin{cases} 0 & x<0 \\ 1 & x \geq 0 \end{cases}$",
            r"文件位于 C:\Users\gml85 目录，不应被识别。",
        ],
    )


def all_docs() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    return [
        doc01_basic(),
        doc02_advanced(),
        doc03_mixed(),
        doc04_edge_cases(),
        doc05_textbook(),
        doc06_v040(),
        doc07_latex(),
    ]


if __name__ == "__main__":
    for p in all_docs():
        print(p)
