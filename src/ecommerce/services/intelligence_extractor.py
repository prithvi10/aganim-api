"""
IntelligenceExtractorService - Extracts strategic intelligence from brand text.

Transforms flat Brand Soul text into structured "Merchant Brain" that enforces
brand logic across all content generation through:
1. Strategic Audit JSON (Archetype, tonal guardrails, linguistic rules)
2. Entity extraction for knowledge graph
3. Triplet building for recursive retrieval
"""

from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)


class BrandArchetype(str, Enum):
    """Carl Jung-inspired brand archetypes."""
    ARTISAN_MASTER = "artisan_master"  # Craftsmanship, tradition, quality
    HERITAGE_HOUSE = "heritage_house"  # History, legacy, authenticity
    MODERN_MINIMALIST = "modern_minimalist"  # Clean, functional, contemporary
    FRIENDLY_LOCAL = "friendly_local"  # Approachable, community, warmth
    LUXURY_CURATOR = "luxury_curator"  # Exclusive, refined, aspirational
    INNOVATIVE_PIONEER = "innovative_pioneer"  # Cutting-edge, disruptive
    SUSTAINABLE_GUARDIAN = "sustainable_guardian"  # Eco-conscious, ethical
    STORYTELLER = "storyteller"  # Narrative-driven, emotional


class EntityType(str, Enum):
    """Types of entities to extract from brand text."""
    MATERIAL = "material"  # silk, ceramic, leather, wood
    TECHNIQUE = "technique"  # hand-forged, kiln-fired, woven
    REGION = "region"  # Kyoto, Arita, Niigata
    ARTISAN = "artisan"  # master craftsman, third-generation
    PROCESS = "process"  # 72-hour fermentation, aging
    CERTIFICATION = "certification"  # JAS organic, UNESCO heritage
    PHILOSOPHY = "philosophy"  # wabi-sabi, yo-no-bi
    TIME_PERIOD = "time_period"  # Edo period, since 1885
    ATTRIBUTE = "attribute"  # durable, lightweight, handmade
    PRODUCT = "product"  # Our pottery, ceramic plates


class TonalGuardrails(BaseModel):
    """Defines the voice boundaries for content generation."""
    formality_level: str = Field(
        description="Range: casual, conversational, professional, formal, ceremonial"
    )
    energy_level: str = Field(
        description="Range: calm, measured, confident, energetic, passionate"
    )
    humor_tolerance: str = Field(
        description="Range: none, subtle, moderate, playful"
    )
    technical_depth: str = Field(
        description="Range: layperson, informed, enthusiast, expert"
    )
    emotional_register: str = Field(
        description="Primary emotion to evoke: trust, excitement, nostalgia, aspiration, comfort"
    )


class LinguisticRules(BaseModel):
    """Specific language patterns to enforce."""
    sentence_style: str = Field(
        description="short_punchy, balanced, flowing_narrative"
    )
    person_voice: str = Field(
        description="first_person_plural (we), second_person (you), third_person (the brand)"
    )
    active_passive_preference: str = Field(
        description="active_preferred, passive_acceptable, mixed"
    )
    jargon_handling: str = Field(
        description="avoid, explain, embrace"
    )


class StrategicIntelligence(BaseModel):
    """Complete strategic audit extracted from brand text."""
    
    # Core Identity
    archetype: BrandArchetype
    archetype_confidence: float = Field(ge=0.0, le=1.0)
    secondary_archetype: Optional[BrandArchetype] = None
    
    # Voice Definition
    tonal_guardrails: TonalGuardrails
    linguistic_rules: LinguisticRules
    
    # Word Banks
    power_words: List[str] = Field(
        description="Words that embody the brand voice (10-20 words)",
        max_items=20
    )
    banned_phrases: List[str] = Field(
        description="Words/phrases that contradict brand identity",
        max_items=20
    )
    
    # Value Propositions
    core_value_props: List[str] = Field(
        description="3-5 key value propositions to weave into content",
        max_items=5
    )
    differentiators: List[str] = Field(
        description="What makes this brand unique vs competitors",
        max_items=5
    )
    
    # Cultural/Regional Cues
    origin_story_hooks: List[str] = Field(
        description="Key narrative elements from brand history",
        max_items=5
    )
    cultural_touchpoints: List[str] = Field(
        description="Cultural references that resonate (e.g., 'Edo-period techniques')",
        max_items=5
    )
    
    # Reasoning Trace
    extraction_reasoning: str = Field(
        description="Brief explanation of why these values were extracted"
    )


class Entity(BaseModel):
    """Extracted entity from text."""
    entity: str = Field(description="The actual text of the entity")
    type: EntityType = Field(description="Type of entity")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in extraction")


class EntityExtractionResult(BaseModel):
    """Result of entity extraction from a chunk."""
    entities: List[Entity] = Field(default_factory=list)


class EntityTriplet(BaseModel):
    """Subject -> Relation -> Object triplet for knowledge graph."""
    subject: str = Field(description="Subject of the relationship")
    subject_type: EntityType
    relation: str = Field(description="Relationship type (e.g., 'uses', 'originates_from')")
    object: str = Field(description="Object of the relationship")
    object_type: EntityType
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source_chunk_id: Optional[int] = Field(None, description="Reference to StoreContext.id")


class TripletExtractionResult(BaseModel):
    """Result of triplet extraction."""
    triplets: List[EntityTriplet] = Field(default_factory=list)


# System prompts for LLM extraction
STRATEGIC_AUDIT_SYSTEM_PROMPT = """You are a brand strategist and linguist.

Your task is to analyze brand text and extract a comprehensive Strategic Intelligence profile that will guide all future content generation.

## ANALYSIS FRAMEWORK

### 1. ARCHETYPE IDENTIFICATION
Identify the primary brand archetype from these options:
- artisan_master: Focus on craftsmanship, tradition, skill
- heritage_house: Emphasis on history, legacy, authenticity
- modern_minimalist: Clean, functional, contemporary
- friendly_local: Approachable, community-oriented
- luxury_curator: Exclusive, refined, aspirational
- innovative_pioneer: Cutting-edge, disruptive
- sustainable_guardian: Eco-conscious, ethical
- storyteller: Narrative-driven, emotional

### 2. TONAL ANALYSIS
Determine appropriate voice parameters:
- Formality: How formal should content be?
- Energy: How energetic or calm?
- Humor: Is humor appropriate?
- Technical depth: How expert is the audience?
- Emotion: What feeling should content evoke?

### 3. LINGUISTIC PATTERNS
Identify writing rules:
- Sentence style preferences
- First/second/third person usage
- Active vs passive voice
- Jargon handling

### 4. WORD BANKS
Extract:
- Power words that embody the brand (10-20)
- Banned phrases that contradict the brand (10-20)

### 5. VALUE EXTRACTION
Identify:
- Core value propositions (3-5)
- Key differentiators (3-5)
- Origin story hooks
- Cultural touchpoints

## OUTPUT REQUIREMENTS
Return a complete StrategicIntelligence JSON object.
Be specific and actionable. Avoid generic platitudes.
Include your reasoning for the archetype selection.
"""


ENTITY_EXTRACTION_PROMPT = """Extract named entities from this brand text.

Entity types to look for:
- MATERIAL: Physical materials (silk, ceramic, wood, leather)
- TECHNIQUE: Craft methods (hand-forged, kiln-fired, woven)
- REGION: Geographic origins (Kyoto, Arita, Niigata)
- ARTISAN: People/craftspeople (master craftsman, founder)
- PROCESS: Production steps (72-hour fermentation, aging)
- CERTIFICATION: Quality marks (JAS organic, UNESCO heritage)
- PHILOSOPHY: Cultural concepts (wabi-sabi, yo-no-bi)
- TIME_PERIOD: Historical references (Edo period, since 1885)
- ATTRIBUTE: Product qualities (durable, lightweight, handmade)
- PRODUCT: Product references (Our pottery, ceramic plates)

For each entity found, provide:
- entity: The actual text
- type: One of the types above
- confidence: 0.0-1.0 how certain you are

Be precise. Only extract entities that are clearly stated or strongly implied.
"""


TRIPLET_EXTRACTION_PROMPT = """Given a list of entities extracted from brand text, identify relationships between them.

For each relationship, create a triplet:
- subject: One entity
- subject_type: Type of the subject entity
- relation: The relationship (e.g., "uses", "originates_from", "trained_in", "located_in", "made_with")
- object: The other entity
- object_type: Type of the object entity
- confidence: 0.0-1.0 how certain you are about this relationship

Example triplets:
- ("Our pottery", PRODUCT) --uses--> ("Arita clay", MATERIAL)
- ("Arita clay", MATERIAL) --originates_from--> ("Saga Prefecture", REGION)
- ("Master Tanaka", ARTISAN) --trained_in--> ("Kyoto techniques", TECHNIQUE)

Only create triplets where there is clear evidence of a relationship in the source text.
"""


class IntelligenceExtractorService:
    """
    Extracts strategic intelligence from raw brand text.
    
    Uses a high-reasoning LLM (gpt-4o) to analyze brand text and produce:
    1. Strategic Audit JSON (archetype, tone, rules)
    2. Entity list for each text chunk
    3. Triplets for knowledge graph
    """
    
    def __init__(self, llm_service):
        """
        Initialize the intelligence extractor.
        
        Args:
            llm_service: LLMService instance for making LLM calls
        """
        self.llm = llm_service
    
    async def extract_strategic_audit(
        self,
        brand_text: str,
        existing_pillars: Optional[List[str]] = None,
    ) -> StrategicIntelligence:
        """
        Extract strategic intelligence from brand text.
        
        Uses a single LLM call with structured output.
        
        Args:
            brand_text: Raw brand text to analyze
            existing_pillars: Optional list of existing brand pillars for context
        
        Returns:
            StrategicIntelligence Pydantic model
        """
        user_prompt = f"""Analyze this brand text and extract strategic intelligence:

BRAND TEXT:
{brand_text}

EXISTING PILLARS (if any):
{existing_pillars or 'None provided'}

Return a complete StrategicIntelligence JSON.
"""
        
        result = await self.llm.generate_structured(
            prompt=user_prompt,
            response_format=StrategicIntelligence,
            system_prompt=STRATEGIC_AUDIT_SYSTEM_PROMPT,
            model="gpt-4o",  # High reasoning for accurate extraction
            temperature=0.2,  # Low temp for consistency
        )
        
        return result
    
    async def extract_entities_from_chunk(
        self,
        chunk_text: str,
    ) -> List[Entity]:
        """
        Extract entities from a single chunk.
        
        Args:
            chunk_text: Text chunk to extract entities from
        
        Returns:
            List of Entity objects
        """
        result = await self.llm.generate_structured(
            prompt=f"Extract entities from: {chunk_text}",
            response_format=EntityExtractionResult,
            system_prompt=ENTITY_EXTRACTION_PROMPT,
            model="gpt-4o-mini",  # Cheaper model for entity extraction
            temperature=0.1,
        )
        return result.entities
    
    async def build_triplets(
        self,
        entities: List[Entity],
        source_text: str,
    ) -> List[EntityTriplet]:
        """
        Build knowledge graph triplets from entities.
        
        Uses LLM to identify relationships between entities.
        
        Args:
            entities: List of extracted entities
            source_text: Source text for context (limited to 3000 chars)
        
        Returns:
            List of EntityTriplet objects
        """
        # Format entities for prompt
        entities_str = "\n".join([
            f"- {e.entity} ({e.type.value})"
            for e in entities[:50]  # Limit to top 50 entities
        ])
        
        user_prompt = f"""
Given these entities:
{entities_str}

And source text:
{source_text[:3000]}

Identify relationships between entities as triplets.
"""
        
        result = await self.llm.generate_structured(
            prompt=user_prompt,
            response_format=TripletExtractionResult,
            system_prompt=TRIPLET_EXTRACTION_PROMPT,
            model="gpt-4o-mini",
            temperature=0.1,
        )
        return result.triplets
