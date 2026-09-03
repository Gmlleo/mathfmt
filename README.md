# MathFmt

[![CI](https://github.com/Gmlleo/mathfmt/actions/workflows/ci.yml/badge.svg)](https://github.com/Gmlleo/mathfmt/actions/workflows/ci.yml)

[中文](#中文) | [English](#english)

MathFmt turns plain-text formulas in Word documents into native Word OMML equations —
stacked fractions, radicals, superscripts, subscripts, derivatives, and standard
mathematical operators — suitable for textbooks, exams, and technical reports.

---

## Quick Start · 快速开始

**Who is this for?** Anyone who writes math-heavy Word documents — teachers preparing
exams, students writing lab reports, engineers drafting technical specs. If you type
formulas like `x^2` or `sqrt(a/b)` in Word and want them rendered as proper equations,
MathFmt is for you.

**适合谁用？** 需要在 Word 里写数学公式的人——老师出试卷、学生写实验报告、工程师写技术文档。如果你在 Word 里输入 `x^2` 或 `sqrt(a/b)` 这样的文本公式，想让它们变成原生公式，MathFmt 就是你的工具。

### Install · 安装

```bash
pip install mathfmt
```

Requirements: Python 3.10–3.14. The only runtime dependency is `lxml`.

### Prefer a GUI? · 想用图形界面？

```bash
mathfmt gui
```

Opens a local page in your browser — drag a `.docx` onto it (or click to choose one),
check off which detected formulas to convert (sensible defaults are pre-checked),
then download the converted file. No other commands needed. Everything runs on
`127.0.0.1`; files never leave the machine.

```bash
mathfmt gui
```

在浏览器打开一个本地页面——把 `.docx` 拖进去（或点击选择文件），勾选要转换的公式（已按合理的默认值预先勾选好），下载转换好的文件即可，不需要再输入别的命令。只监听
`127.0.0.1`，文件不会离开这台电脑。

### Check your environment · 检查环境

```bash
mathfmt doctor
```

Prints MathFmt, Python, lxml/libxml2/libxslt versions, backend availability, and platform info —
useful before filing a bug report.

### Convert a document · 转换文档

```bash
# One-step conservative conversion (high-confidence formulas only)
mathfmt convert input.docx --output output.docx

# Scan first, review candidates, then apply (recommended for production)
mathfmt scan input.docx --report candidates.json
mathfmt apply input.docx --review candidates.json --report preview.json --dry-run
mathfmt apply input.docx --review candidates.json --output output.docx --report result.json
mathfmt apply input.docx --review candidates.json --output output.docx --report result.json --strict
```

For detailed workflow, see [docs/workflow.md](docs/workflow.md).

You can mark formulas explicitly in DOCX text with `$...$` for inline equations or
`$$...$$` for display equations. MathFmt removes the delimiters when it inserts the
native Word equation.

Reviewed formulas can span multiple aligned lines. Put `\\` or a real line break in
the candidate's `linear` value, for example `a = b \\ c = d`; MathFmt creates one
native Word equation array and aligns the rows at their first relation symbol.

Piecewise formulas support both `f(x) = {0, x<0; 1, x>=0}` and
`cases(0 if x<0; 1 if x>=0)`. Both render as a native Word expression with a left
brace and aligned expression/condition columns.

Basic chemistry notation is also supported: `H2O`, `CO2`, and `NaCl` use upright
element symbols and native subscripts; reactions such as `2H2 + O2 -> 2H2O` support
`->`, `<->`, and `=>`, plus `(aq)/(g)/(l)/(s)` states and `->[heat]` annotations.

Physics notation includes stacked partial derivatives (`partial f / partial x` or
`∂f/∂x`), tensor indices such as `T_i^j`, and bra-ket forms including
`<phi|psi>`, `⟨φ|ψ⟩`, and `bra(phi) ket(psi)`.

Custom symbol aliases can be supplied with `--aliases`. A minimal JSON profile is:

```json
{
  "name": "engineering",
  "aliases": {
    "ohm": "Ω",
    "mapsTo": "↦"
  }
}
```

Pass the same profile to each review-first command:

```bash
mathfmt scan input.docx --report candidates.json --aliases symbols.json
mathfmt apply input.docx --review candidates.json --output output.docx --report result.json --aliases symbols.json
```

Alias tokens may add one Unicode mathematical symbol but cannot replace MathFmt
keywords such as `sqrt`, `lim`, `sum`, or `partial`. Reports record the profile
name, absolute path, symbol count, and SHA-256 digest.

MathFmt 1.0 also supports trusted custom formula recognizers through repeatable
`--recognizer module:object` options or the stable Python API. See
[docs/plugins.md](docs/plugins.md) for the typed plugin contract and conflict rules.

---

## Status

**Stable (v1.2.0).** Feature-complete cross-platform OMML conversion with a stable
Python API, deterministic custom recognizers, structured safety reports, batch
processing, WPS/LibreOffice compatibility checks, a 100-page performance gate, and
an optional local drag-and-drop GUI (`mathfmt gui`) with a candidate review step
and a reverse OMML → text converter for tooling built on top of MathFmt.

---

## 中文

MathFmt 将 DOCX 中的普通文本公式排版为 Word 原生 OMML 公式。

### 快速示例

| 输入（纯文本） | 输出（Word 原生公式） |
|---|---|
| `ds(t)/dt` | 堆叠分式 d s(t) / d t |
| `s'(t) = -s''(t)` | 导数分数形式 |
| `sqrt(x^2 + 1)` | 根号 √(x²+1) |
| `x^3 + p1` | 上标 x³ + 下标 p₁ |
| `x != 0` | x ≠ 0 |
| `sin(x) + cos(x)` | sin(x) + cos(x) |
| `lim(p->0)` | lim 带下置 p→0 |
| `a/(b+c)` | 堆叠分式 |
| `e^(p1*t)` | e 的 p₁t 次幂 |
| `1(t)` | u(t)（单位阶跃） |
| `Delta + pi` | Δ + π |
| `x, y, z` | 逗号分隔序列 |
| `H2O` | 直立元素符号与原生下标 H₂O |
| `2H2 + O2 -> 2H2O` | 化学反应式与原生箭头 |

### 兼容性

| | Windows 10/11 | macOS | Linux |
|---|---|---|---|
| Python 3.10–3.14 | ✔ | ✔ | ✔ |
| 公式扫描 | ✔ | ✔ | ✔ |
| OMML 公式输出（内置 Python 后端） | ✔ | ✔ | ✔ |
| OMML 公式输出（Office XSL 后端） | ✔ | ✔¹ | ✔¹ |
| Word 渲染 | ✔ | ✔² | — |
| WPS Writer 渲染 | ✔³ | — | ◐⁴ |

¹ 需手动指定 `MML2OMML.XSL` 路径（`--xsl`）。  
² macOS 版 Microsoft Word。
³ 已使用 WPS Writer 12.0 完成隐藏打开、DOCX 往返保存和 PDF 视觉验收。
⁴ `--compatibility wps` 离线检查可在 Linux 运行；Linux 版 WPS 的原生视觉验收仍需手工执行。

### 命令

```powershell
mathfmt scan    input.docx --report candidates.json   # 扫描公式候选
mathfmt scan    input.docx --report candidates.json --recognizer my_plugin:Recognizer  # 自定义识别器
mathfmt apply   input.docx --review candidates.json --report preview.json --dry-run  # 仅预览，不写 DOCX
mathfmt apply   input.docx --review candidates.json --output out.docx --report result.json  # 审核后转换
mathfmt apply   input.docx --review candidates.json --output out.docx --report result.json --strict  # 失败则不写输出
mathfmt convert input.docx                           # 保守一键转换
mathfmt convert "folder/*.docx" --output-dir converted --batch-report batch.json  # 批量转换
mathfmt validate input.docx                           # 离线结构验证
mathfmt validate input.docx --compatibility wps       # WPS 兼容性检查
mathfmt gui                                           # 打开本地图形界面（拖拽转换）
mathfmt doctor                                        # 环境诊断
mathfmt update                                        # 检查 GitHub 更新
```

### 更新

```powershell
mathfmt update              # 检查更新并显示安装命令
mathfmt update --check      # CI 模式：有更新时退出码 1，最新时退出码 0
mathfmt update --pre        # 包含预发布版本
mathfmt update --force      # 跳过缓存，立即检查 GitHub
```

检测结果缓存 1 小时。也可直接运行：

```powershell
pip install --upgrade mathfmt
```

### 版本路线

| 版本 | 内容 |
|---|---|
| **0.1.0** (2026-06-21) | 基础扫描、审核、转换；原生 Word 公式输出；Windows + Office |
| **0.2.0** (2026-06-21) | 跨平台内置 OMML；置信度评分；独立验证；积分/求和/矩阵/向量/分段 |
| **0.2.1** (2026-06-21) | GitHub 自更新；缓存隔离；SemVer 预发布支持 |
| **0.2.2** (2026-06-21) | CI/Ruff 修复；缓存崩溃修复；退出码修正；验证报告版本 |
| **0.2.3** (2026-06-22) | Parser 修复（省略号/阶乘/大型算子/边界/深度）；文档与示例完善 |
| **0.3.0** (2026-06-25) | 结构化转换报告；dry-run 预览；严格模式；失败公式提示；更好的错误信息 |
| **0.4.0** (2026-08-06) | LaTeX 分隔符；多行对齐；分段函数；化学与物理记号；自定义符号别名 |
| **0.5.0** (2026-08-07) | 批量转换；WPS 离线兼容性检查与 Windows 往返渲染验收 |
| **1.0.0** (2026-08-08) | 稳定 API 与 SemVer；插件钩子；100 页性能门禁；Python 3.14 |
| **1.1.0** (2026-08-31) | `mathfmt gui`：本地浏览器拖拽界面，无需终端命令 |
| **1.2.0** (2026-09-03) | `mathfmt gui` 转换前逐条审核公式；解析错误附带提示；`omml_to_text` 反向转换；可选独立 exe 打包 |

### 更多文档

- [公式语法参考](docs/formula-syntax.md) — 完整预处理规则、语法、MathML 映射和限制
- [工作流指南](docs/workflow.md) — 安装、审核流程、错误处理、CI 使用
- [稳定 API](docs/api.md) — 1.x 兼容承诺、弃用政策和异常边界
- [自定义识别器](docs/plugins.md) — 类型化插件 API、CLI 加载和冲突规则
- [性能](docs/performance.md) — 100 页/800 公式基准与 CI 门禁
- [示例](examples/README.md) — 从零开始的测试文档准备和转换教程
- [路线图](ROADMAP.md) — 版本规划与功能展望

### 维护

v1.0 已进入稳定维护模式，没有计划中的功能版本；仅在必要时处理安全或兼容性问题。
单人维护（Leo），尽力响应。欢迎提交 Issue 和 PR，也可通过
[gml853503962@gmail.com](mailto:gml853503962@gmail.com) 联系。安全漏洞请参阅
[SECURITY.md](SECURITY.md)。

---

## English

MathFmt converts plain-text formulas in DOCX files into native Word OMML equations.

### Quick Examples

| Input (plain text in DOCX) | Output (native Word equation) |
|---|---|
| `ds(t)/dt` | Stacked fraction d s(t) / d t |
| `s'(t) = -s''(t)` | Leibniz fraction derivatives |
| `sqrt(x^2 + 1)` | Radical √(x²+1) |
| `x^3 + p1` | Superscript x³ + subscript p₁ |
| `x != 0` | x ≠ 0 |
| `sin(x) + cos(x)` | sin(x) + cos(x) |
| `lim(p->0)` | lim with under-script p→0 |
| `a/(b+c)` | Stacked fraction |
| `e^(p1*t)` | e raised to p₁t |
| `1(t)` | u(t) (unit step) |
| `Delta + pi` | Δ + π |
| `x, y, z` | Comma-separated sequence |
| `H2O` | Upright element symbols with native subscript H₂O |
| `2H2 + O2 -> 2H2O` | Chemical reaction with a native arrow |
| `∂f/∂x` | Stacked partial-derivative fraction |
| `T_i^j` | Combined tensor subscript and superscript |
| `<phi\|psi>` | Native angle-delimited bra-ket `⟨phi\|psi⟩` |

### Compatibility

| | Windows 10/11 | macOS | Linux |
|---|---|---|---|
| Python 3.10–3.14 | ✔ | ✔ | ✔ |
| Formula scanning | ✔ | ✔ | ✔ |
| OMML output (built-in Python backend) | ✔ | ✔ | ✔ |
| OMML output (Office XSL backend) | ✔ | ✔¹ | ✔¹ |
| Word rendering | ✔ | ✔² | — |
| WPS Writer rendering | ✔³ | — | ◐⁴ |

¹ Manual `--xsl` path required for Office XSL backend.  
² Microsoft Word for Mac.
³ Round-trip DOCX save and PDF visual QA completed with WPS Writer 12.0.
⁴ The offline `--compatibility wps` profile runs on Linux; native Linux WPS visual QA remains manual.

### Commands

```powershell
mathfmt scan    input.docx --report candidates.json   # Scan formula candidates
mathfmt scan    input.docx --report candidates.json --recognizer my_plugin:Recognizer  # Custom recognizer
mathfmt apply   input.docx --review candidates.json --report preview.json --dry-run  # Preview only
mathfmt apply   input.docx --review candidates.json --output out.docx --report result.json  # Apply reviewed candidates
mathfmt apply   input.docx --review candidates.json --output out.docx --report result.json --strict  # Do not write output on failures
mathfmt convert input.docx                           # Conservative one-step conversion
mathfmt convert "folder/*.docx" --output-dir converted --batch-report batch.json  # Batch conversion
mathfmt validate input.docx                           # Offline structure validation
mathfmt validate input.docx --compatibility wps       # WPS compatibility lint
mathfmt gui                                           # Open the local drag-and-drop GUI
mathfmt doctor                                        # Environment check
mathfmt update                                        # Check GitHub for updates
```

### Updating

```powershell
mathfmt update              # Check for updates and show install commands
mathfmt update --check      # CI mode: exit 1 when update available, 0 when current
mathfmt update --pre        # Include pre-release versions
mathfmt update --force      # Skip cache, re-check GitHub immediately
```

Check results are cached for 1 hour. You can also upgrade directly:

```powershell
pip install --upgrade mathfmt
```

### Version Roadmap

| Version | Scope |
|---|---|
| **0.1.0** (2026-06-21) | Scan, review, convert; native Word OMML; Windows + Office |
| **0.2.0** (2026-06-21) | Cross-platform built-in OMML; confidence scoring; validate; integrals, sums, matrices |
| **0.2.1** (2026-06-21) | GitHub self-update; cache isolation; SemVer pre-release support |
| **0.2.2** (2026-06-21) | CI/Ruff fixes; cache crash fix; exit code correction; validate version |
| **0.2.3** (2026-06-22) | Parser fixes (ellipsis, factorial, n-ary, 1(t), x_bar, boundary); depth validation; docs & examples |
| **0.3.0** (2026-06-25) | Structured conversion reports; dry-run preview; strict mode; failed-formula warnings; better errors |
| **0.4.0** (2026-08-06) | LaTeX delimiters, aligned and piecewise equations, chemistry and physics notation, and symbol aliases |
| **0.5.0** (2026-08-07) | Batch conversion, offline WPS compatibility lint, and Windows WPS round-trip rendering QA |
| **1.0.0** (2026-08-08) | Stable API and SemVer, plugin hooks, 100-page performance gate, Python 3.14 |
| **1.1.0** (2026-08-31) | `mathfmt gui`: a local browser drag-and-drop interface, no terminal commands needed |
| **1.2.0** (2026-09-03) | `mathfmt gui` per-candidate review before converting; plain-language parse-error hints; `omml_to_text` reverse conversion; optional standalone exe packaging |

### Further Reading

- [Formula Syntax Reference](docs/formula-syntax.md) — every preprocessing rule, the full grammar, MathML output mapping, and known limitations
- [Workflow Guide](docs/workflow.md) — step-by-step install, review flow, troubleshooting, CI usage
- [Stable API](docs/api.md) — 1.x compatibility contract, deprecation policy, and exception boundaries
- [Custom Recognizers](docs/plugins.md) — typed plugin API, CLI loading, and deterministic conflicts
- [Performance](docs/performance.md) — 100-page/800-formula benchmark and CI gate
- [Examples](examples/README.md) — walkthrough from a blank test document to formatted output
- [Roadmap](ROADMAP.md) — completed release history and stable-maintenance status

### Maintenance

v1.0 is in stable maintenance mode with no planned feature releases; only necessary
security or compatibility maintenance is expected. Single-maintainer project (Leo),
best-effort response. Issues and pull requests are
welcome. You can also contact the maintainer at
[gml853503962@gmail.com](mailto:gml853503962@gmail.com). See
[CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and
[SECURITY.md](SECURITY.md).

---

## Contributing

Issues and pull requests are welcome.

## License

MIT License. Copyright (c) 2026 Leo.
