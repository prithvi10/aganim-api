# Strategic Intelligence Service - Technical Specification

## Overview

Transform flat Brand Soul text into a structured "Merchant Brain" that enforces brand logic across all content generation through:
1. **Strategic Audit JSON** - Archetype, tonal guardrails, linguistic rules
2. **Knowledge Graph Lite** - Entity triplets for recursive retrieval
3. **Enhanced RAG** - Entity-aware context retrieval
4. **Agent Integration** - Dynamic system prompt injection

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BRAND SOUL UI INPUT                                │
│                     (Raw text from onboarding wizard)                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    INTELLIGENCE EXTRACTOR SERVICE                            │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐  │
│  │  Strategic Audit    │  │  Entity Extractor   │  │  Triplet Builder    │  │
│  │  (Archetype, Tone)  │  │  (NER-style)        │  │  (Knowledge Graph)  │  │
│  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
    ┌───────────────────────────┐       ┌───────────────────────────────────┐
    │    Strategic Intelligence │       │         Vector DB (pgvector)      │
    │    JSON (Shop.brand_intel)│       │  ┌─────────────────────────────┐  │
    │                           │       │  │  StoreContext + entities[]   │  │
    │  - archetype             │       │  │  metadata: {entities, triplets}│  │
    │  - tonal_guardrails      │       │  └─────────────────────────────┘  │
    │  - linguistic_rules      │       │                                    │
    │  - banned_phrases        │       │  ┌─────────────────────────────┐  │
    │  - power_words           │       │  │  EntityIndex (new table)     │  │
    │  - value_props           │       │  │  subject, relation, object   │  │
    └───────────────────────────┘       │  └─────────────────────────────┘  │
                    │                   └───────────────────────────────────┘
                    │                                   │
                    └─────────────┬─────────────────────┘
                                  ▼
    ┌─────────────────────────────────────────────────────────────────────────┐
    │                      ENHANCED RAG SERVICE                                │
    │                                                                          │
    │   1. Vector similarity search (existing)                                 │
    │   2. Entity-based expansion (NEW)                                        │
    │   3. Triplet traversal for "Complete Context"                           │
    └─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
    ┌─────────────────────────────────────────────────────────────────────────┐
    │                      AGENT SYSTEM PROMPT                                 │
    │                                                                          │
    │   ### OPERATIONAL RULES (from Strategic Intelligence)                    │
    │   Archetype: Heritage Artisan                                            │
    │   Tone: Sophisticated but approachable                                   │
    │   MUST use: [crafted, heritage, artisan...]                             │
    │   NEVER use: [cheap, discount, mass-produced...]                        │
    │                                                                          │
    │   ### BRAND CONTEXT (from Enhanced RAG)                                  │
    │   [Relevant chunks with entity-aware expansion]                          │
    └─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Strategic Audit JSON Schema

The high-reasoning LLM will extract this structured JSON from raw brand text:

```python
# src/ecommerce/services/intelligence_extractor.py

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

class BrandArchetype(str, Enum):
    """Carl Jung-inspired brand archetypes."""
    ARTISAN_MASTER = "artisan_master"      # Craftsmanship, tradition, quality
    HERITAGE_HOUSE = "heritage_house"       # History, legacy, authenticity
    MODERN_MINIMALIST = "modern_minimalist" # Clean, functional, contemporary
    FRIENDLY_LOCAL = "friendly_local"       # Approachable, community, warmth
    LUXURY_CURATOR = "luxury_curator"       # Exclusive, refined, aspirational
    INNOVATIVE_PIONEER = "innovative_pioneer" # Cutting-edge, disruptive
    SUSTAINABLE_GUARDIAN = "sustainable_guardian" # Eco-conscious, ethical
    STORYTELLER = "storyteller"             # Narrative-driven, emotional

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
```

---

## 3. Knowledge Graph Lite (Entity Triplets)

### 3.1 Entity Types

```python
class EntityType(str, Enum):
    """Types of entities to extract from brand text."""
    MATERIAL = "material"           # silk, ceramic, leather, wood
    TECHNIQUE = "technique"         # hand-forged, kiln-fired, woven
    REGION = "region"               # Kyoto, Arita, Niigata
    ARTISAN = "artisan"             # master craftsman, third-generation
    PROCESS = "process"             # 72-hour fermentation, aging
    CERTIFICATION = "certification" # JAS organic, UNESCO heritage
    PHILOSOPHY = "philosophy"       # wabi-sabi, yo-no-bi
    TIME_PERIOD = "time_period"     # Edo period, since 1885
    ATTRIBUTE = "attribute"         # durable, lightweight, handmade
```

### 3.2 Triplet Schema

```python
class EntityTriplet(BaseModel):
    """Subject -> Relation -> Object triplet for knowledge graph."""
    subject: str           # "Our ceramics"
    subject_type: EntityType
    relation: str          # "are_made_using"
    object: str            # "Arita porcelain techniques"
    object_type: EntityType
    confidence: float      # 0.0-1.0
    source_chunk_id: Optional[int] = None  # Reference to StoreContext.id

# Example triplets:
# ("Our pottery", MATERIAL) --uses--> ("Arita clay", MATERIAL)
# ("Arita clay", MATERIAL) --originates_from--> ("Saga Prefecture", REGION)
# ("Our process", PROCESS) --takes--> ("72 hours", TIME_PERIOD)
# ("Master Tanaka", ARTISAN) --trained_in--> ("Kyoto", REGION)
```

### 3.3 Database Schema Addition

```sql
-- Add to db_models.py
CREATE TABLE brand_entities (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR NOT NULL REFERENCES shops(domain),
    
    -- Subject
    subject TEXT NOT NULL,
    subject_type VARCHAR NOT NULL,
    
    -- Relation
    relation VARCHAR NOT NULL,
    
    -- Object
    object TEXT NOT NULL,
    object_type VARCHAR NOT NULL,
    
    -- Metadata
    confidence FLOAT DEFAULT 1.0,
    source_chunk_id INTEGER REFERENCES store_context(id),
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Indexes for traversal
    INDEX idx_subject (shop_id, subject_type, subject),
    INDEX idx_object (shop_id, object_type, object)
);

-- Add strategic_intelligence JSON to shops table
ALTER TABLE shops ADD COLUMN strategic_intelligence JSONB;
ALTER TABLE shops ADD COLUMN strategic_intelligence_updated_at TIMESTAMP;

-- Add entity tags to store_context metadata
-- (Already supported via metadata_json, just document the schema)
-- metadata_json.entities = ["material:silk", "region:kyoto", "technique:hand-woven"]
```

---

## 4. Implementation Details

### 4.1 Intelligence Extractor Service

```python
# src/ecommerce/services/intelligence_extractor.py

class IntelligenceExtractorService:
    """
    Extracts strategic intelligence from raw brand text.
    
    Uses a high-reasoning LLM (gpt-4o) to analyze brand text and produce:
    1. Strategic Audit JSON (archetype, tone, rules)
    2. Entity list for each text chunk
    3. Triplets for knowledge graph
    """
    
    def __init__(self, llm_service: "LLMService"):
        self.llm = llm_service
    
    async def extract_strategic_audit(
        self,
        brand_text: str,
        existing_pillars: List[str] = None,
    ) -> StrategicIntelligence:
        """
        Extract strategic intelligence from brand text.
        
        Uses a single LLM call with structured output.
        """
        system_prompt = STRATEGIC_AUDIT_SYSTEM_PROMPT
        user_prompt = f"""
Analyze this brand text and extract strategic intelligence:

BRAND TEXT:
{brand_text}

EXISTING PILLARS (if any):
{existing_pillars or 'None provided'}

Return a complete StrategicIntelligence JSON.
"""
        
        result = await self.llm.generate_structured(
            prompt=user_prompt,
            response_format=StrategicIntelligence,
            system_prompt=system_prompt,
            model="gpt-4o",  # High reasoning for accurate extraction
            temperature=0.2,  # Low temp for consistency
        )
        
        return result
    
    async def extract_entities_from_chunk(
        self,
        chunk_text: str,
    ) -> List[Dict]:
        """
        Extract entities from a single chunk.
        
        Returns list of {entity, type, confidence}.
        """
        # Can use gpt-4o-mini for cost efficiency
        result = await self.llm.generate_structured(
            prompt=f"Extract entities from: {chunk_text}",
            response_format=EntityExtractionResult,
            model="gpt-4o-mini",
            temperature=0.1,
        )
        return result.entities
    
    async def build_triplets(
        self,
        entities: List[Dict],
        source_text: str,
    ) -> List[EntityTriplet]:
        """
        Build knowledge graph triplets from entities.
        
        Uses LLM to identify relationships between entities.
        """
        result = await self.llm.generate_structured(
            prompt=f"""
Given these entities: {entities}
And source text: {source_text}

Identify relationships between entities as triplets.
""",
            response_format=TripletExtractionResult,
            model="gpt-4o-mini",
            temperature=0.1,
        )
        return result.triplets
```

### 4.2 Updated Brand Ingest Flow

```python
# Update src/ecommerce/services/brand_ingest_service.py

async def ingest_brand_context_with_intelligence(
    db: Session,
    *,
    shop_id: str,
    raw_texts: list[dict],
    extract_intelligence: bool = True,  # NEW: Enable intelligence extraction
    max_len: int = 500,
    overlap: int = 50,
) -> dict:
    """
    Enhanced brand ingestion with strategic intelligence extraction.
    """
    # Step 1: Existing cleaning and chunking
    cleaned_items = []
    for item in raw_texts:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        cleaned = _clean_brand_text(text)
        cleaned_items.append({...})
    
    # Step 2: Process chunks with entity extraction (NEW)
    chunks = []
    chunk_meta = []
    all_entities = []
    
    extractor = IntelligenceExtractorService(llm_service)
    
    for item in cleaned_items:
        blob = item.get("clean_blob") or {}
        en_text = blob.get("en", {}).get("clean_text") or ""
        
        for chunk in chunk_text(en_text, max_len=max_len, overlap=overlap):
            if not chunk.content.strip():
                continue
            
            # Extract entities for this chunk (NEW)
            if extract_intelligence:
                entities = await extractor.extract_entities_from_chunk(chunk.content)
                all_entities.extend(entities)
            else:
                entities = []
            
            chunks.append(chunk.content)
            chunk_meta.append({
                "source_url": item.get("source_url"),
                "chunk_index": chunk.chunk_index,
                "entities": [f"{e['type']}:{e['entity']}" for e in entities],  # NEW
            })
    
    # Step 3: Extract Strategic Intelligence (NEW)
    strategic_intel = None
    if extract_intelligence:
        full_text = "\n\n".join([
            item.get("clean_blob", {}).get("en", {}).get("clean_text", "")
            for item in cleaned_items
        ])
        strategic_intel = await extractor.extract_strategic_audit(
            brand_text=full_text,
            existing_pillars=existing_pillars,
        )
    
    # Step 4: Build triplets (NEW)
    triplets = []
    if extract_intelligence and all_entities:
        triplets = await extractor.build_triplets(
            entities=all_entities,
            source_text=full_text[:3000],  # Limit context size
        )
    
    # Step 5: Store chunks with entity metadata
    vectors = embed_texts(chunks)
    for content, meta, vec in zip(chunks, chunk_meta, vectors):
        row = StoreContext(
            shop_id=shop_id,
            content=content,
            embedding=vec,
            metadata_json={
                **meta,
                "entities": meta.get("entities", []),  # Entity tags for filtering
            },
        )
        db.add(row)
    
    # Step 6: Store triplets in brand_entities table (NEW)
    for triplet in triplets:
        entity_row = BrandEntity(
            shop_id=shop_id,
            subject=triplet.subject,
            subject_type=triplet.subject_type,
            relation=triplet.relation,
            object=triplet.object,
            object_type=triplet.object_type,
            confidence=triplet.confidence,
        )
        db.add(entity_row)
    
    # Step 7: Store strategic intelligence on Shop (NEW)
    if strategic_intel:
        shop = db.query(Shop).filter(Shop.domain == shop_id).first()
        if shop:
            shop.strategic_intelligence = strategic_intel.model_dump()
            shop.strategic_intelligence_updated_at = datetime.now(timezone.utc)
    
    db.commit()
    
    return {
        "inserted": len(chunks),
        "strategic_intelligence": strategic_intel.model_dump() if strategic_intel else None,
        "triplet_count": len(triplets),
        "entity_count": len(all_entities),
    }
```

### 4.3 Enhanced RAG Service

```python
# Update src/agentic_core/rag/rag_service.py

class RAGService:
    """Enhanced RAG with entity-aware retrieval."""
    
    async def get_complete_context(
        self,
        db: Session,
        shop_id: str,
        product_text: str,
        limit: int = 5,
    ) -> Dict:
        """
        Get complete brand context with entity expansion.
        
        Returns:
        {
            "chunks": [...],           # Vector similarity results
            "related_entities": [...], # Entities found in chunks
            "expanded_context": [...], # Additional chunks via entity traversal
            "strategic_rules": {...},  # Strategic intelligence JSON
        }
        """
        # Step 1: Standard vector similarity search
        base_chunks = await self.get_brand_context(
            db=db,
            shop_id=shop_id,
            product_text=product_text,
            limit=limit,
        )
        
        # Step 2: Extract entities mentioned in product text
        product_entities = await self._extract_product_entities(product_text)
        
        # Step 3: Find chunks that share entities (entity-based expansion)
        expanded_chunks = []
        if product_entities:
            expanded_chunks = await self._get_chunks_by_entities(
                db=db,
                shop_id=shop_id,
                entities=product_entities,
                exclude_ids=[c.get("id") for c in base_chunks],
                limit=3,
            )
        
        # Step 4: Traverse knowledge graph for related context
        related_triplets = await self._traverse_knowledge_graph(
            db=db,
            shop_id=shop_id,
            seed_entities=product_entities,
            depth=2,  # 2 hops max
        )
        
        # Step 5: Get strategic intelligence
        strategic_intel = await self._get_strategic_intelligence(db, shop_id)
        
        return {
            "chunks": base_chunks,
            "expanded_chunks": expanded_chunks,
            "related_triplets": related_triplets,
            "strategic_rules": strategic_intel,
        }
    
    async def _get_chunks_by_entities(
        self,
        db: Session,
        shop_id: str,
        entities: List[str],
        exclude_ids: List[int],
        limit: int = 3,
    ) -> List[Dict]:
        """
        Find chunks that contain specified entities.
        
        Uses JSONB containment query on metadata_json.entities.
        """
        # PostgreSQL JSONB query for entity overlap
        query = db.query(StoreContext).filter(
            StoreContext.shop_id == shop_id,
            ~StoreContext.id.in_(exclude_ids),
        )
        
        # Filter chunks where entities array overlaps with our entities
        # This requires JSONB array overlap operator &&
        entity_conditions = []
        for entity in entities[:5]:  # Limit to top 5 entities
            entity_conditions.append(
                StoreContext.metadata_json["entities"].contains([entity])
            )
        
        if entity_conditions:
            from sqlalchemy import or_
            query = query.filter(or_(*entity_conditions))
        
        rows = query.limit(limit).all()
        
        return [{"content": r.content, "metadata": r.metadata_json} for r in rows]
    
    async def _traverse_knowledge_graph(
        self,
        db: Session,
        shop_id: str,
        seed_entities: List[str],
        depth: int = 2,
    ) -> List[Dict]:
        """
        Traverse knowledge graph from seed entities.
        
        Returns triplets connected to the seed entities within N hops.
        """
        visited = set()
        results = []
        current_level = seed_entities
        
        for _ in range(depth):
            if not current_level:
                break
            
            # Find triplets where subject or object matches current entities
            triplets = db.query(BrandEntity).filter(
                BrandEntity.shop_id == shop_id,
                or_(
                    BrandEntity.subject.in_(current_level),
                    BrandEntity.object.in_(current_level),
                )
            ).all()
            
            next_level = []
            for t in triplets:
                key = f"{t.subject}-{t.relation}-{t.object}"
                if key not in visited:
                    visited.add(key)
                    results.append({
                        "subject": t.subject,
                        "relation": t.relation,
                        "object": t.object,
                        "confidence": t.confidence,
                    })
                    next_level.extend([t.subject, t.object])
            
            current_level = [e for e in next_level if e not in visited]
        
        return results
```

### 4.4 Agent Integration

```python
# Update src/agentic_core/agents/base.py

class BaseAgent(ABC):
    """Base agent with strategic intelligence integration."""
    
    async def perceive(self, state: MissionState) -> AgentContext:
        """Enhanced perception with strategic intelligence."""
        
        # Existing: get learned rules
        learned_rules = await self.memory.get_learned_preferences(self.role_name)
        
        # NEW: Get strategic intelligence
        strategic_intel = None
        if state.db:
            strategic_intel = await self.services.rag._get_strategic_intelligence(
                state.db, 
                self.shop_id
            )
        
        context = AgentContext(
            raw_input=state.raw_input,
            learned_rules=learned_rules,
            strategic_intelligence=strategic_intel,  # NEW
        )
        
        return await self._perceive_domain(state, context)


# Update src/agentic_core/agents/context.py

@dataclass
class AgentContext:
    """Context with strategic intelligence."""
    
    raw_input: Dict[str, Any]
    brand_context: List[Dict] = field(default_factory=list)
    learned_rules: List[Dict] = field(default_factory=list)
    external_data: Dict[str, Any] = field(default_factory=dict)
    strategic_intelligence: Optional[Dict] = None  # NEW
    
    def get_operational_rules_prompt(self) -> str:
        """
        Format strategic intelligence as operational rules for system prompt.
        """
        if not self.strategic_intelligence:
            return ""
        
        intel = self.strategic_intelligence
        
        rules = f"""
### OPERATIONAL RULES (Brand Intelligence)

**ARCHETYPE:** {intel.get('archetype', 'Not defined')}
This brand embodies the {intel.get('archetype', '')} archetype.

**TONAL GUARDRAILS:**
- Formality: {intel.get('tonal_guardrails', {}).get('formality_level', 'professional')}
- Energy: {intel.get('tonal_guardrails', {}).get('energy_level', 'measured')}
- Emotion: {intel.get('tonal_guardrails', {}).get('emotional_register', 'trust')}

**LINGUISTIC RULES:**
- Sentence style: {intel.get('linguistic_rules', {}).get('sentence_style', 'balanced')}
- Voice: {intel.get('linguistic_rules', {}).get('person_voice', 'second_person')}

**MUST USE (Power Words):**
{', '.join(intel.get('power_words', [])[:10])}

**NEVER USE (Banned Phrases):**
{', '.join(intel.get('banned_phrases', [])[:10])}

**VALUE PROPOSITIONS TO WEAVE IN:**
{chr(10).join(['- ' + v for v in intel.get('core_value_props', [])])}

**CULTURAL TOUCHPOINTS:**
{chr(10).join(['- ' + c for c in intel.get('cultural_touchpoints', [])])}
"""
        return rules.strip()
```

### 4.5 Updated Rewriter/Marketing Prompts

```python
# Update src/ecommerce/agents/rewriter/agent.py

def _build_system_prompt(self, state: MissionState, context: AgentContext) -> str:
    """Build system prompt with strategic intelligence."""
    
    prompt_parts = [REWRITER_SYSTEM_PROMPT]
    
    # NEW: Inject operational rules FIRST (highest priority)
    operational_rules = context.get_operational_rules_prompt()
    if operational_rules:
        prompt_parts.insert(0, operational_rules)
    
    # Existing: tone, locale, brand context, learned preferences
    # ... rest of existing code ...
    
    return "\n\n".join(prompt_parts)
```

---

## 5. LLM Prompts

### 5.1 Strategic Audit Extraction Prompt

```python
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
```

### 5.2 Entity Extraction Prompt

```python
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

For each entity found, provide:
- entity: The actual text
- type: One of the types above
- confidence: 0.0-1.0 how certain you are

Be precise. Only extract entities that are clearly stated or strongly implied.
"""
```

---

## 6. Database Migrations

```python
# Add to db_models.py

class BrandEntity(Base):
    """Knowledge graph triplets for brand intelligence."""
    __tablename__ = "brand_entities"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String, ForeignKey("shops.domain"), index=True, nullable=False)
    
    # Triplet: Subject -> Relation -> Object
    subject = Column(String, nullable=False)
    subject_type = Column(String, nullable=False)
    relation = Column(String, nullable=False)
    object = Column(String, nullable=False)
    object_type = Column(String, nullable=False)
    
    # Metadata
    confidence = Column(Numeric(3, 2), default=1.0)
    source_chunk_id = Column(Integer, ForeignKey("store_context.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Add columns to Shop model
# strategic_intelligence = Column(JSONB, nullable=True)
# strategic_intelligence_updated_at = Column(DateTime(timezone=True), nullable=True)
```

---

## 7. API Endpoints

```python
# Add to src/ecommerce/api/controller.py

@router.post("/api/admin/brand-intelligence/extract")
async def extract_brand_intelligence(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Extract strategic intelligence from existing brand context.
    
    Triggers the intelligence extraction pipeline on stored brand text.
    """
    # Get existing brand context
    shop_record = db.query(Shop).filter(Shop.domain == shop).first()
    if not shop_record or not shop_record.brand_context:
        raise HTTPException(status_code=404, detail="No brand context found")
    
    # Extract intelligence
    extractor = IntelligenceExtractorService(llm_service)
    brand_text = shop_record.brand_context.get("en", {}).get("clean_text", "")
    
    intel = await extractor.extract_strategic_audit(brand_text)
    
    # Store
    shop_record.strategic_intelligence = intel.model_dump()
    shop_record.strategic_intelligence_updated_at = datetime.now(timezone.utc)
    db.commit()
    
    return {"status": "success", "intelligence": intel.model_dump()}


@router.get("/api/admin/brand-intelligence")
async def get_brand_intelligence(
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """Get stored strategic intelligence for a shop."""
    shop_record = db.query(Shop).filter(Shop.domain == shop).first()
    if not shop_record:
        raise HTTPException(status_code=404, detail="Shop not found")
    
    return {
        "intelligence": shop_record.strategic_intelligence,
        "updated_at": shop_record.strategic_intelligence_updated_at,
    }
```

---

## 8. Implementation Order

| Step | Component | Effort | Dependencies |
|------|-----------|--------|--------------|
| 1 | `StrategicIntelligence` Pydantic models | 2 hours | None |
| 2 | `IntelligenceExtractorService` | 4 hours | Step 1 |
| 3 | `BrandEntity` DB model + migration | 1 hour | None |
| 4 | Update `brand_ingest_service` | 3 hours | Steps 1-3 |
| 5 | Enhanced `RAGService.get_complete_context` | 4 hours | Steps 3-4 |
| 6 | Update `AgentContext` with operational rules | 2 hours | Step 5 |
| 7 | Update `BaseAgent.perceive` | 2 hours | Step 6 |
| 8 | Update Rewriter/Marketing prompts | 2 hours | Steps 6-7 |
| 9 | API endpoints | 2 hours | Steps 2, 4 |
| 10 | Testing & integration | 4 hours | All |

**Total: ~26 hours (~3-4 days)**

---

## 9. Testing Strategy

### Unit Tests
- `test_intelligence_extractor.py` - Mock LLM responses, verify JSON parsing
- `test_entity_extraction.py` - Verify entity recognition accuracy
- `test_triplet_builder.py` - Verify relationship extraction

### Integration Tests
- `test_enhanced_rag.py` - End-to-end context retrieval with expansion
- `test_agent_with_intelligence.py` - Verify prompt injection works

### Manual Validation
- Compare content quality before/after intelligence injection
- Verify banned phrases are not used
- Verify power words appear in output
