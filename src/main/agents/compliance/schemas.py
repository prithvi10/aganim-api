"""
Compliance Agent Pydantic Schemas

Structured output models for the ComplianceAgent.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class ComplianceCheck(BaseModel):
    """
    Response format for ComplianceAgent.
    
    Used to validate product content against compliance rules
    (FDA, FTC, etc.).
    """
    
    has_violations: bool = Field(
        description="Whether any compliance issues were found"
    )
    flags: List[str] = Field(
        default_factory=list,
        description="List of compliance violation flags"
    )
    severity: str = Field(
        description="Overall severity: low, medium, high"
    )
    suggested_fixes: List[str] = Field(
        default_factory=list,
        description="Suggested fixes for each violation"
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Explanation of the compliance analysis"
    )


class ComplianceViolation(BaseModel):
    """
    Detailed information about a single compliance violation.
    """
    
    violation_type: str = Field(
        description="Type of violation: FDA, FTC, General"
    )
    description: str = Field(
        description="Description of the violation"
    )
    original_text: str = Field(
        description="The problematic text from the content"
    )
    suggested_fix: Optional[str] = Field(
        default=None,
        description="Suggested replacement text"
    )
    severity: str = Field(
        description="Severity: low, medium, high"
    )
