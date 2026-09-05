# MathFmt 1.x API Stability Contract

MathFmt 1.0 establishes a stable Python API for applications that scan, convert,
and validate DOCX equations. The contract applies to names exported by
`mathfmt.__all__`; modules, names, and attributes beginning with `_` are private.

## Supported runtime

- CPython 3.10 through 3.14
- `lxml` 5.0 or newer
- Windows, macOS, and Linux
- Built-in Python OMML generation on every supported platform

## Stable exports

| Export | Purpose |
|---|---|
| `formula_to_mathml(source, aliases=None)` | Parse one linear formula into MathML |
| `mathml_to_omml(math, transform=None)` | Convert MathML — the built-in Python backend unless a `transform` is supplied |
| `mathml_to_omml_py(math)` | Convert MathML with the cross-platform Python backend |
| `omml_to_text(omath_elem)` | Convert a native ``m:oMath``/``m:oMathPara`` element back to MathFmt's linear formula syntax |
| `scan_docx(input_path, report_path, alias_profile=None, *, recognizers=())` | Create a review report |
| `apply_docx(input_path, review_path, output_path, result_path, xsl_path=None, *, ...)` | Apply a reviewed report |
| `validate_docx(input_path, *, review_path=None, xsl_path=None, alias_profile=None, compatibility=None)` | Validate package, OMML, coverage, and compatibility |
| `find_xsl(explicit=None)` | Locate Microsoft's optional transform |
| `load_alias_profile(path)` / `AliasProfile` | Load reproducible symbol aliases |
| `load_recognizer(spec)` / `FormulaRecognizer` / `FormulaCandidate` | Extend candidate detection |
| `check_for_updates(...)` / `UpdateInfo` | Query release information |
| `FormulaError`, `RecognizerError`, `DocxSecurityError`, `OmmlConversionError` | Catch supported failure categories |

**Backend default.** The library's default is the built-in Python backend:
`mathml_to_omml(math)` with no `transform` never touches Microsoft's stylesheet.
This is the opposite of the CLI's default, which auto-detects the Office XSL and
prefers it — see `docs/workflow.md` §1. Pass `find_xsl()`'s result as the
`transform` (or `xsl_path`) if you want the library to match CLI output.

The exact exported-name list and call signatures are protected by
`tests/test_public_api.py`. New optional keyword parameters and new exports may be
added in a compatible 1.x minor release; existing parameters will not be removed,
renamed, reordered, or made more restrictive within 1.x.

## Semantic-versioning guarantees

MathFmt follows Semantic Versioning:

- Patch releases fix defects or security issues without changing supported behavior.
- Minor releases may add syntax, report fields, CLI options, or optional API features.
- Removing or incompatibly changing a stable export, accepted input, documented exit
  code, or report field requires a new major version.

Dictionary results and JSON reports are extensible: consumers must ignore unknown
fields. Existing fields keep their meaning and type throughout 1.x. A new report
schema version is introduced only when a reader must branch to interpret a change.

## Deprecation policy

If a stable API ever needs replacement, MathFmt will:

1. document the replacement in the changelog and this API reference;
2. emit `DeprecationWarning` from the old API;
3. keep the old behavior for at least one complete minor-release cycle and six
   months; and
4. remove it only in a major release.

Security fixes may disable behavior immediately only when retaining it would expose
users to a material vulnerability; such a change will be called out prominently.

## Compatibility boundaries

The following are not stable API: private names, human-readable CLI prose, log text,
temporary filenames, object identities, and XML prefix choices. Native MathML/OMML
elements, JSON values, exit codes, and documented conflict rules are stable at their
semantic level rather than by byte-for-byte serialization.

Paths passed to the 1.0 API must be `pathlib.Path` instances. Input DOCX files are
never overwritten; `apply_docx` rejects an output path equal to its input path.

For the recognizer extension contract, see [plugins.md](plugins.md). For report
fields and exit codes, see [workflow.md](workflow.md).
