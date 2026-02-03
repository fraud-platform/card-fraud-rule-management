"""
AST/JSON Compiler for Fraud Rule Governance API.

This package provides deterministic compilation of approved RuleSets
into executable JSON AST for the Quarkus runtime engine.

Key Components:
- validator: Validates condition tree structure and semantics
- compiler: Main compilation logic for RuleSets
- canonicalizer: Ensures deterministic JSON output

Design Principles:
- Determinism: Same input produces byte-for-byte identical output
- Validation: All references are verified before compilation
- Explicitness: Evaluation modes and policies are declared, not inferred
"""

from app.compiler.canonicalizer import canonicalize_json
from app.compiler.compiler import compile_ruleset
from app.compiler.validator import validate_condition_tree

__all__ = [
    "compile_ruleset",
    "validate_condition_tree",
    "canonicalize_json",
]
