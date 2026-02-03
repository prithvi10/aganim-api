"""
MissionState - The shared state clipboard passed between agents.

This is the central data structure that holds all information about
a product optimization mission as it flows through the agent pipeline.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal, Any
from sqlalchemy.orm import Session


@dataclass
class MissionState:
    """
    Shared state clipboard passed between agents during a mission.
    
    This acts as a "clipboard" that agents read from and write to,
    allowing information to flow through the pipeline while maintaining
    a complete audit trail.
    
    Attributes:
        product_id: Shopify product ID being optimized
        shop_id: Shop domain identifier
        plan_tier: User's subscription tier (affects agent workflow)
        raw_input: Original product data from Shopify
        db: Database session for persistence operations
        
        draft_content: Generated content from CopywriterAgent
        pricing_analysis: Analysis from PriceScoutAgent
        compliance_flags: Issues found by ComplianceAgent
        
        logs: Audit trail of agent actions
        status: Current mission status
    """
    
    # Required identifiers
    product_id: str
    shop_id: str
    plan_tier: Literal["Free", "Basic", "Standard", "Pro"]
    raw_input: Dict[str, Any]
    
    # Database session (not serialized)
    db: Optional[Session] = None
    
    # Evolving artifacts (populated by agents)
    draft_content: Optional[str] = None
    draft_title: Optional[str] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    pricing_analysis: Optional[Dict[str, Any]] = None
    compliance_flags: List[str] = field(default_factory=list)
    discovered_values: List[Dict[str, Any]] = field(default_factory=list)
    
    # Marketing agent artifacts
    seo_alt_text: Optional[str] = None
    seo_insights: Optional[Dict[str, Any]] = None         # LSI keywords, search intent
    seo_recommendations: Optional[Dict[str, Any]] = None  # Competitive edge + buyer intent
    ctr_check: Optional[Dict[str, Any]] = None            # PST formula validation
    serp_insights: Optional[List[Dict[str, Any]]] = None  # Top 3 Google competitors
    social_hooks: Optional[List[Dict[str, Any]]] = None   # Social media hooks
    seasonal_campaign: Optional[Dict[str, Any]] = None    # Seasonal campaign data
    
    # Audit trail
    logs: List[str] = field(default_factory=list)
    
    # Mission status
    status: str = "PENDING"
    # Valid statuses:
    # - PENDING: Not started
    # - IN_PROGRESS: Agent is currently working
    # - AWAITING_APPROVAL: Agent completed, waiting for merchant decision (Continue/Regenerate/Skip)
    # - DRAFT_READY: Content generated, awaiting review
    # - COMPLIANCE_REVIEW: Compliance issues found
    # - COMPLETED: Mission finished successfully
    # - ERROR: Something went wrong
    
    # Error tracking
    error_message: Optional[str] = None
    
    # Metadata
    target_locale: Optional[str] = None
    source_locale: Optional[str] = None
    
    # Token usage tracking for fair_use integration
    accumulated_usage: Optional[Dict[str, Any]] = None
    
    # Step-by-step journey tracking
    current_agent_index: int = 0               # Index of the current/next agent to run
    skipped_agents: List[str] = field(default_factory=list)  # Agents skipped by merchant
    agent_outputs: Dict[str, Any] = field(default_factory=dict)  # Each agent's output stored separately
    regeneration_feedback: Optional[str] = None  # Merchant feedback for regeneration
    workflow_agents: List[str] = field(default_factory=list)  # List of agent names in workflow order

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert state to a JSON-serializable dictionary.
        
        Used for:
        - SSE streaming to frontend
        - Persisting to database
        - Logging/debugging
        
        Returns:
            Dict representation of state (excludes db session)
        """
        return {
            "product_id": self.product_id,
            "shop_id": self.shop_id,
            "plan_tier": self.plan_tier,
            "raw_input": self.raw_input,
            "draft_content": self.draft_content,
            "draft_title": self.draft_title,
            "seo_title": self.seo_title,
            "seo_description": self.seo_description,
            "pricing_analysis": self.pricing_analysis,
            "compliance_flags": self.compliance_flags,
            "discovered_values": self.discovered_values,
            # Marketing agent artifacts
            "seo_alt_text": self.seo_alt_text,
            "seo_insights": self.seo_insights,
            "seo_recommendations": self.seo_recommendations,
            "ctr_check": self.ctr_check,
            "serp_insights": self.serp_insights,
            "social_hooks": self.social_hooks,
            "seasonal_campaign": self.seasonal_campaign,
            # Audit and status
            "logs": self.logs,
            "status": self.status,
            "error_message": self.error_message,
            "target_locale": self.target_locale,
            "source_locale": self.source_locale,
            # Usage tracking
            "accumulated_usage": self.accumulated_usage,
            # Step-by-step journey tracking
            "current_agent_index": self.current_agent_index,
            "skipped_agents": self.skipped_agents,
            "agent_outputs": self.agent_outputs,
            "regeneration_feedback": self.regeneration_feedback,
            "workflow_agents": self.workflow_agents,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], db: Optional[Session] = None) -> "MissionState":
        """
        Create a MissionState from a dictionary.
        
        Used for:
        - Restoring from database
        - Deserializing from API request
        
        Args:
            data: Dictionary with state fields
            db: Optional database session to attach
        
        Returns:
            MissionState instance
        """
        return cls(
            product_id=data.get("product_id", ""),
            shop_id=data.get("shop_id", ""),
            plan_tier=data.get("plan_tier", "Free"),
            raw_input=data.get("raw_input", {}),
            db=db,
            draft_content=data.get("draft_content"),
            draft_title=data.get("draft_title"),
            seo_title=data.get("seo_title"),
            seo_description=data.get("seo_description"),
            pricing_analysis=data.get("pricing_analysis"),
            compliance_flags=data.get("compliance_flags", []),
            discovered_values=data.get("discovered_values", []),
            # Marketing agent artifacts
            seo_alt_text=data.get("seo_alt_text"),
            seo_insights=data.get("seo_insights"),
            seo_recommendations=data.get("seo_recommendations"),
            ctr_check=data.get("ctr_check"),
            serp_insights=data.get("serp_insights"),
            social_hooks=data.get("social_hooks"),
            seasonal_campaign=data.get("seasonal_campaign"),
            # Audit and status
            logs=data.get("logs", []),
            status=data.get("status", "PENDING"),
            error_message=data.get("error_message"),
            target_locale=data.get("target_locale"),
            source_locale=data.get("source_locale"),
            # Usage tracking
            accumulated_usage=data.get("accumulated_usage"),
            # Step-by-step journey tracking
            current_agent_index=data.get("current_agent_index", 0),
            skipped_agents=data.get("skipped_agents", []),
            agent_outputs=data.get("agent_outputs", {}),
            regeneration_feedback=data.get("regeneration_feedback"),
            workflow_agents=data.get("workflow_agents", []),
        )

    def add_log(self, message: str) -> None:
        """Add a log message to the audit trail."""
        self.logs.append(message)

    def set_error(self, message: str) -> None:
        """Set error status with message."""
        self.status = "ERROR"
        self.error_message = message
        self.logs.append(f"ERROR: {message}")
