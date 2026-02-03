"""
Autonomous testing library for live API validation.

This library provides:
- Scenario definition and parsing (YAML-based)
- HTTP client for scenario execution
- Database assertion evaluation for state-aware testing
- Seeding module for deterministic test data
- Multi-layer validation engine (HTTP, OpenAPI, domain, side effects)
- Enhanced HTML reporter with step-by-step details
- Reporting (JSON + HTML)
"""

from .db_assertions import (
    DbAssertionEvaluator,
    DbAssertionResult,
    DbConnectionManager,
    SkipConditionEvaluator,
    create_db_evaluator,
)
from .http_client import (
    ScenarioExecutor,
    ScenarioHttpClient,
    extract_json_path,
)
from .reporter import (
    EnhancedHtmlReporter,
    ScenarioExecutionDetail,
    StepArtifact,
    StepExecutionDetail,
    TestRunDetail,
)
from .scenario import (
    DbAssertion,
    ExecutionContext,
    ExpectCondition,
    OnConflictHandler,
    Scenario,
    ScenarioResult,
    ScenarioStep,
    SkipCondition,
    StepResult,
    StepSaveSpec,
    load_scenario_from_yaml,
    scenario_from_dict,
)
from .seeding import (
    ApiSeeder,
    DbSeeder,
    HybridSeeder,
    SeedingMode,
    create_seeder,
)
from .validation import (
    DomainValidator,
    HttpValidator,
    MultiLayerValidator,
    OpenApiValidator,
    SideEffectsValidator,
    ValidationError,
    ValidationLayer,
    ValidationResult,
)

__all__ = [
    "ApiSeeder",
    "DbAssertion",
    "DbAssertionEvaluator",
    "DbAssertionResult",
    "DbConnectionManager",
    "DbSeeder",
    "DomainValidator",
    "ExecutionContext",
    "ExpectCondition",
    "EnhancedHtmlReporter",
    "HttpValidator",
    "HybridSeeder",
    "MultiLayerValidator",
    "OnConflictHandler",
    "OpenApiValidator",
    "Scenario",
    "ScenarioExecutionDetail",
    "ScenarioExecutor",
    "ScenarioHttpClient",
    "ScenarioResult",
    "ScenarioStep",
    "SeedingMode",
    "SideEffectsValidator",
    "StepArtifact",
    "StepExecutionDetail",
    "StepResult",
    "SkipCondition",
    "SkipConditionEvaluator",
    "StepSaveSpec",
    "TestRunDetail",
    "ValidationError",
    "ValidationLayer",
    "ValidationResult",
    "create_db_evaluator",
    "create_seeder",
    "extract_json_path",
    "load_scenario_from_yaml",
    "scenario_from_dict",
]
