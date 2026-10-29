"""Compatibility shim: upstream calls this module ``anticipation.tokenize``.

The customized tokenizer in this repo lives in ``tokenize_custom.py``; the
humaneval experiment scripts import ``anticipation.tokenize``, so this module
re-exports it under the expected name.
"""

from anticipation.tokenize_custom import *  # noqa: F401,F403
from anticipation.tokenize_custom import (
    extract_instruments,
    extract_random,
    extract_spans,
    maybe_tokenize,
    tokenize,
    tokenize_ia,
)

__all__ = [
    "extract_instruments",
    "extract_random",
    "extract_spans",
    "maybe_tokenize",
    "tokenize",
    "tokenize_ia",
]
