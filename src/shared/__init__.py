"""
shared - Cross-cutting infrastructure used by both agentic_core and ecommerce.

Contains logging, utilities, database engine, security, and configuration
that are domain-agnostic and shared across all packages.

Dependency rule: shared has ZERO imports from agentic_core or ecommerce.
"""
