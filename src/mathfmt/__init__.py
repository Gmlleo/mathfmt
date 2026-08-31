"""MathFmt public API."""

from ._version import __version__
from .aliases import AliasProfile, load_alias_profile
from .core import FormulaError, apply_docx, find_xsl, formula_to_mathml, mathml_to_omml, scan_docx
from .docxio import DocxSecurityError
from .omml import OmmlConversionError, mathml_to_omml_py, omml_to_text
from .plugins import FormulaCandidate, FormulaRecognizer, RecognizerError, load_recognizer
from .update import UpdateInfo, check_for_updates
from .validate import validate_docx

__all__ = [
    "AliasProfile",
    "DocxSecurityError",
    "FormulaCandidate",
    "FormulaError",
    "FormulaRecognizer",
    "OmmlConversionError",
    "RecognizerError",
    "UpdateInfo",
    "__version__",
    "apply_docx",
    "check_for_updates",
    "find_xsl",
    "formula_to_mathml",
    "load_alias_profile",
    "load_recognizer",
    "mathml_to_omml",
    "mathml_to_omml_py",
    "omml_to_text",
    "scan_docx",
    "validate_docx",
]
