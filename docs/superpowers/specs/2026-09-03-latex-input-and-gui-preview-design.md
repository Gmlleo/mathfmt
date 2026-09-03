# MathFmt v1.3 设计：LaTeX 输入子集与 GUI 预览

- 状态：已批准，待实现
- 日期：2026-09-03
- 版本目标：v1.3.0（次版本号，向后兼容）

## 1. 背景与目标

MathFmt 1.2 的解析器只接受 MathFmt 自己的线性语法。文档里出现的
`\frac{a}{b}`、`\alpha`、`\sum_{i=1}^{n}` 今天是硬解析失败：`TOKEN_RE`
（`core.py:373`）没有反斜杠分支，`MATH_CHARS`（`core.py:66`）也不含反斜杠，
这类跨度连扫描候选都不会成为。而论文、教材与 AI 生成内容里的公式默认就是
LaTeX 形态。

同时，GUI 的候选清单（`gui.py:585` 的 `candidateRowHtml`）只显示源文本和置信度
徽章，不懂语法的用户无法判断该不该勾选，解析失败的候选也没有任何修复路径。

本版本解决两件事：

1. **进得来** —— 支持一个封闭的、有文档的 LaTeX 宏子集作为输入写法。
2. **敢勾选** —— GUI 为每条候选渲染公式预览，并允许行内编辑后重新预览。

两项都严格向后兼容：今天报错的输入变成可转换，今天能转换的输入行为一字不变。

### 与 ROADMAP 的关系

`ROADMAP.md` 声明 1.x 处于稳定维护模式、不计划扩展支持语法。本设计是对该策略的
一次**明示修订**，需要在 ROADMAP 中记录 v1.3 条目并说明修订理由；它不改变任何
既有语法的含义，也不改变 `docs/api.md` 的稳定 API 承诺。

## 2. LaTeX 前端：`src/mathfmt/latex.py`

### 2.1 架构决策

新增独立模块做**纯文本层的宏展开**：`LaTeX 文本 → MathFmt 线性语法`，其结果再交给
现有的 `preprocess_formula` → `tokenize` → `Parser` 管线。

**不修改 `TOKEN_RE`，不修改 `Parser` 的既有分支。**

理由：本版本目标子集中的绝大多数构造，MathFmt 线性语法里都已有等价写法（例外见
第 3 节）。把 LaTeX 处理隔离在一个不认识 lxml、不认识 MathML 的模块里，可以独立
测试；并且非 LaTeX 输入的执行路径一个字节都不变，这是"现有行为零回归"最强的保证。

### 2.2 接口

```python
def expand_latex(source: str) -> str:
    """把 LaTeX 宏展开为 MathFmt 线性语法；遇到子集外的宏抛 FormulaError。"""

def contains_latex_macro(text: str) -> bool:
    """判断文本中是否出现已知宏，供扫描器使用；不做展开。"""
```

`formula_to_mathml`（`core.py:1353`）中只增加一处分支：若
`contains_latex_macro(source)` 为真，则先经 `expand_latex` 再走原有流程。

这两个函数**不进入 `__init__.py` 的 `__all__`**。稳定 API 的每一次新增都是永久
承诺，目前没有外部调用需求。

### 2.3 支持的宏（v1.3 完整清单）

**结构**

| LaTeX | 展开为 | 落到的现有能力 |
|---|---|---|
| `\frac{a}{b}`、`\dfrac`、`\tfrac` | `(a)/(b)` | binary `/` → `m:mfrac` |
| `\sqrt{x}` | `sqrt(x)` | `Node("sqrt")` → `m:msqrt` |
| `x^{n+1}`、`x_{i}` | `x^(n+1)`、`x_(i)` | `msup` / `msub` / `msubsup` |
| `\left( ... \right)` | `( ... )` | `parse_group` |
| `\sum_{i=1}^{n} f` | `sum(i=1,n) f` | `Node("nary")` 带上下限 |
| `\int_{a}^{b} f`、`\prod_{...}^{...}` | `int(a,b) f`、`prod(...)` | 同上 |
| `\lim_{x \to 0}` | `lim(x->0)` | `Node("limit")` → `m:munder` |

**符号**

| LaTeX | 展开为 |
|---|---|
| `\alpha` … `\omega`、`\Gamma` … `\Omega` | 对应 Unicode 字母（词法器已接受 `[Α-Ωα-ω]`） |
| `\leq \geq \neq \approx \equiv` | `≤ ≥ ≠ ≈ ≡` |
| `\pm \times \cdot \div` | `± × · ÷` |
| `\to \rightarrow \Rightarrow \leftrightarrow` | `→ → ⇒ <->` |
| `\in \notin \subset \subseteq \cup \cap` | `∈ ∉ ⊂ ⊆ ∪ ∩` |
| `\infty` | `∞` |
| `\sin \cos \tan \log \ln \exp` | 去掉反斜杠的同名函数 |
| `\,` `\;` `\!` `\quad` `\qquad` | 空字符串（间距宏丢弃） |

`\partial` 仅在偏导形态中受支持：`\partial f / \partial x` 展开为 `∂f/∂x`，由现有
预处理（`core.py:387`）转成 `partial(f,x)`。**单独出现的 `\partial` 不在支持范围内**
—— `TOKEN_RE` 的 IDENT 字符类不含 `∂`，展开后会触发词法错误。同理 `\nabla`（`∇`）
与 `\mp`（`∓`）也不在本版本范围内：前者不在 IDENT 字符类中，后者不在 OP 字符类与
`OP_add` 集合中；支持它们就必须修改 `TOKEN_RE`，与第 2.1 节的前提冲突。见第 10 节。

**环境**

| LaTeX | 展开为 | 落到的现有能力 |
|---|---|---|
| `\begin{matrix\|pmatrix\|bmatrix} a & b \\ c & d \end{...}` | `[[a,b],[c,d]]` | `_parse_matrix` |
| `\begin{cases} 0 & x<0 \\ 1 & x\ge 0 \end{cases}` | `{0, x<0; 1, x>=0}` | `piecewise` |
| `\begin{aligned} a=b \\ c=d \end{aligned}`（含 `align`/`align*`） | `a = b \\ c = d` | `split_multiline_formula` |

另有两个构造需要新增原生能力，不在上表中，见第 3 节：`\bar \overline \hat \vec
\dot \ddot`（重音）与 `\text{} \mathrm{}`（直立文本）。

### 2.4 展开顺序

1. **环境**（`\begin{...}...\end{...}`）先处理。环境内的 `&` 是列分隔符、`\\` 是行
   分隔符，必须在此阶段消费或转为 MathFmt 的对应语义。
2. **带参宏**（`\frac`、`\sqrt`、`\text` 等）按嵌套结构展开，需正确处理嵌套花括号。
3. **上下限**（`_{...}^{...}`）绑定到紧邻的 `\sum`/`\int`/`\prod`/`\lim`。
4. **无参符号宏**做表替换。
5. **间距宏**丢弃。

`\\` 的双重含义是本模块最需要注意的地方：在 `aligned` 语境中它是行分隔符，展开后
必须原样保留交给 `split_multiline_formula`（`core.py:1368`）；在其它语境中出现的
`\\` 视为不支持并报错。

## 3. 新增的原生能力（仅此两项）

### 3.1 重音

重音在 MathFmt 线性语法中没有等价写法，`identifier_mathml`（`core.py:842`）与
MathML 输出映射中都不存在 overline/hat/vec。按解析器已有的函数式扩展惯例
（`partial(f,x)`、`bra(a)`、`ket(b)`、`braket(a,b)`，见 `_parse_physics_function`）
新增一个 **MathFmt 原生构造**，而不是为 LaTeX 开专用后门：

```
accent(x, bar)   accent(F, vec)   accent(y, hat)   accent(q, dot)   accent(q, ddot)
```

- 新 AST 节点 `accent`，第二参数限定为 `bar|vec|hat|dot|ddot`，其它值报错。
- MathML：`m:mover` 且带 `accent="true"`，上标位为对应组合字符
  （`‾` / `→` / `^` / `˙` / `¨`）。
- OMML：`omml.py:168` 现在无条件把 `mover` 送进 `_limit_upper` → `m:limUpp`。改为按
  `accent` 属性分流 —— 带 `accent="true"` 走新的 `m:acc`（含 `m:accPr/m:chr`），
  不带的保持现状。**老路径行为不变。**
- `omml_to_text` 增加 `m:acc` → `accent(x,bar)` 的反向支持，避免 v1.2 的反向能力
  出现新缺口。
- LaTeX 侧：`\bar` `\overline` → `accent(x,bar)`；`\hat` `\vec` `\dot` `\ddot` 同理。
- 附带收益：不使用 LaTeX 的用户也获得了重音能力。

### 3.2 文本原子

`\text{已知}` 与 `\mathrm{d}` 需要一个直立文本原子。复用化学式已在使用的直立
`m:mtext` 通路，展开为 `text(已知)`，同样作为 MathFmt 原生构造加入解析器。

## 4. 不支持 `\sqrt[n]{x}`

`parse_atom`（`core.py:771`）中 `sqrt` 只接受一个分组，`node_to_mathml`
（`core.py:933`）只有 `m:msqrt` 没有 `m:mroot`。`sqrt(x,3)` 会把 "x, 3" 整体塞进
根号内**静默错渲**。

因此 n 次根不在 v1.3 范围内，且 `expand_latex` 必须对 `\sqrt[` **显式抛
`FormulaError`**（hint 指明不支持 n 次根），绝不可展开为 `sqrt(x,3)`。错误优于错渲。

## 5. 扫描器

两处增量。**不放宽 `MATH_CHARS`**（不加入反斜杠），因此通用扫描的行为完全不变，
`C:\Users\gml85` 一类路径不可能成为候选。

1. `_latex_delimited_spans`（`core.py:1469`）增加 `\( ... \)`（行内）与
   `\[ ... \]`（display），与现有 `$`/`$$` 同级，**高置信**，`apply` 时同样剥离
   定界符只插入公式。
2. 新增 `_latex_macro_spans`，在 `candidate_spans`（`core.py:1579`）中挂于化学式
   探测之后、通用字符扫描之前。跨度需同时满足：含至少一个已知宏、且
   `formula_to_mathml` 实际解析成功（沿用 `_physics_spans` 的 try/except 守卫）。
   置信度为 **medium**，进入候选列表供人工审核，`convert` 不自动转换。

`likely_code` 的代码排除逻辑保持不变；显式定界符跨度沿用既有的"只扫描显式跨度"
处理方式。

## 6. GUI 预览与行内编辑

- `/scan` 返回的每条候选新增两个字段：`linear`（解析用文本）与 `mathml`
  （序列化后的 `<math>` 字符串）。
- 新增 `POST /preview/<token>`：请求体为 linear 文本，返回 `{ok: true, mathml}`
  或 `{ok: false, error, hint}`。复用现有 `_SessionStore` 做会话校验，沿用既有的
  长度限制与错误响应约定（非 ASCII 说明经 `explain=` 传递，不进状态行）。
- 前端：每条候选下方插入 MathML 交由浏览器原生渲染；linear 文本可编辑，失焦后请求
  `/preview` 刷新预览与错误提示。
- `/apply` 的选择载荷由 `id → bool` 扩展为 `id → {selected, linear?}`。服务端把
  编辑后的 `linear` 写回 `candidates.json` 再调用 `apply_docx` —— 这正是 apply 早已
  支持的"手工修改 candidates.json"审核流程，转换侧无需新逻辑。
- 浏览器不支持 MathML 时降级为纯文本并给出提示，不视为错误。

## 7. 错误处理

- 子集外的宏一律抛 `FormulaError`，`hint` 点名具体宏，例如
  `MathFmt 不支持 \substack`。绝不猜测 —— 与 v1.2 为 `omml_to_text` 定下的
  "不可逆构造抛 `OmmlConversionError` 而非猜测" 是同一条原则。
- **错误列号不做到原始 LaTeX 的精确映射**（本版本明确接受的代价）：`FormulaError`
  的 `source` 保留原始 LaTeX 文本，`position` 落在展开后的文本上，定位依靠 `hint`
  中的宏名。
- 展开阶段与解析阶段的错误使用同一个 `FormulaError` 类型，因而自动出现在 scan 报告的
  `parse_error_details`、apply 报告的 `error_details` 和 GUI 候选列表中，无需新的
  错误通道。

## 8. 测试

- 新增 `tests/test_latex.py`：表驱动覆盖第 2.3 节列出的**每一个**宏；每个不支持的
  宏都必须报错且 `hint` 非空；`\sqrt[3]{x}` 必须报错而非静默错渲。
- `test_core.py`：`accent` 与 `text` 的 解析 → MathML → OMML → `omml_to_text` 往返；
  `mover` 不带 `accent` 属性时仍走 `m:limUpp`。
- `test_core.py` 扫描：`\( ... \)` 与 `\[ ... \]` 为高置信；裸宏为中置信；
  `C:\Users\gml85` 不成为候选；`$12.00$` 仍被忽略。
- `test_gui.py`：`/preview` 的成功与失败路径、编辑后的 linear 确实进入产物、
  会话隔离与失效会话的处理。
- `tests/acceptance/gen_docs.py` 新增 doc07（LaTeX 混排文档），纳入 CI 的
  LibreOffice 渲染门禁。
- **回归保证**：现有测试一行不改即应全部通过。

## 9. 文档

- `docs/formula-syntax.md` 新增第 10 节 "LaTeX input subset"：完整支持表 + 明确的
  不支持清单（含 `\sqrt[n]{}`、`\nabla`/`\mp`/裸 `\partial` 与错误列号的已知限制）。
- `docs/workflow.md`：LaTeX 文档的扫描/审核流程说明。
- `README.md`：双语简述。
- `CHANGELOG.md`：v1.3.0 条目。
- `ROADMAP.md`：v1.3 条目 + 策略修订说明。
- `docs/api.md`：无变化（未新增导出符号）。

## 10. 明确不做（YAGNI）

- LaTeX 输出 / DOCX → TeX 反向导出
- `\substack` `\overbrace` `\underbrace` `\mathcal` `\mathbb` `\operatorname` `\binom`
- `\sqrt[n]{x}`（见第 4 节）
- `\nabla`、`\mp`，以及单独出现的 `\partial`（见第 2.3 节）
- 原始 LaTeX 文本中的精确错误列号
- GUI 中的段落上下文高亮
- 用户自定义宏（`\newcommand`）
