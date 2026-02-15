"""
Unit tests for IntelligenceExtractorService.

Tests Pydantic models, extraction prompts, and service methods.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.ecommerce.services.intelligence_extractor import (
    BrandArchetype,
    EntityType,
    TonalGuardrails,
    LinguisticRules,
    StrategicIntelligence,
    Entity,
    EntityExtractionResult,
    EntityTriplet,
    TripletExtractionResult,
    IntelligenceExtractorService,
    STRATEGIC_AUDIT_SYSTEM_PROMPT,
    ENTITY_EXTRACTION_PROMPT,
    TRIPLET_EXTRACTION_PROMPT,
)

from src.test.fixtures.brand_soul_fixtures import (
    BRAND_SOUL_RAW_TEXT,
    STRATEGIC_INTELLIGENCE,
)


# =============================================================================
# Tests: Pydantic Model Validation
# =============================================================================

class TestPydanticModels:
    """Verify Pydantic models validate and serialize correctly."""

    def test_brand_archetype_enum_values(self):
        assert BrandArchetype.ARTISAN_MASTER == "artisan_master"
        assert BrandArchetype.HERITAGE_HOUSE == "heritage_house"
        assert BrandArchetype.LUXURY_CURATOR == "luxury_curator"

    def test_entity_type_enum_values(self):
        assert EntityType.MATERIAL == "material"
        assert EntityType.TECHNIQUE == "technique"
        assert EntityType.REGION == "region"
        assert EntityType.PHILOSOPHY == "philosophy"

    def test_tonal_guardrails_creation(self):
        tg = TonalGuardrails(
            formality_level="professional",
            energy_level="calm",
            humor_tolerance="subtle",
            technical_depth="enthusiast",
            emotional_register="trust",
        )
        assert tg.formality_level == "professional"
        assert tg.energy_level == "calm"

    def test_linguistic_rules_creation(self):
        lr = LinguisticRules(
            sentence_style="flowing_narrative",
            person_voice="first_person_plural",
            active_passive_preference="active_preferred",
            jargon_handling="embrace",
        )
        assert lr.person_voice == "first_person_plural"

    def test_strategic_intelligence_creation(self):
        """Full StrategicIntelligence model with all fields."""
        si = StrategicIntelligence(
            archetype=BrandArchetype.ARTISAN_MASTER,
            archetype_confidence=0.95,
            secondary_archetype=BrandArchetype.HERITAGE_HOUSE,
            tonal_guardrails=TonalGuardrails(
                formality_level="professional",
                energy_level="calm",
                humor_tolerance="subtle",
                technical_depth="enthusiast",
                emotional_register="trust",
            ),
            linguistic_rules=LinguisticRules(
                sentence_style="flowing_narrative",
                person_voice="first_person_plural",
                active_passive_preference="active_preferred",
                jargon_handling="embrace",
            ),
            power_words=["handcrafted", "heritage", "artisan"],
            banned_phrases=["cheap", "bargain", "deal"],
            core_value_props=["Fourth-generation Arita porcelain"],
            differentiators=["Only workshop still using 1923 celadon recipe"],
            origin_story_hooks=["Founded 1923 in Arita"],
            cultural_touchpoints=["Yō-no-bi philosophy"],
            extraction_reasoning="Strong artisan archetype based on handcraft emphasis.",
        )
        assert si.archetype == BrandArchetype.ARTISAN_MASTER
        assert si.archetype_confidence == 0.95
        assert len(si.power_words) == 3
        assert len(si.banned_phrases) == 3

    def test_strategic_intelligence_model_dump(self):
        """model_dump should produce serializable dict."""
        si = StrategicIntelligence(
            archetype=BrandArchetype.ARTISAN_MASTER,
            archetype_confidence=0.9,
            tonal_guardrails=TonalGuardrails(
                formality_level="professional",
                energy_level="calm",
                humor_tolerance="subtle",
                technical_depth="enthusiast",
                emotional_register="trust",
            ),
            linguistic_rules=LinguisticRules(
                sentence_style="balanced",
                person_voice="second_person",
                active_passive_preference="active_preferred",
                jargon_handling="explain",
            ),
            power_words=["crafted"],
            banned_phrases=["cheap"],
            core_value_props=["Quality"],
            differentiators=["Unique"],
            origin_story_hooks=["Founded 1923"],
            cultural_touchpoints=["Tea ceremony"],
            extraction_reasoning="Artisan focus.",
        )
        dumped = si.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["archetype"] == "artisan_master"
        assert isinstance(dumped["tonal_guardrails"], dict)
        assert isinstance(dumped["linguistic_rules"], dict)

    def test_strategic_intelligence_from_fixture(self):
        """Our fixture data should be valid StrategicIntelligence."""
        si = StrategicIntelligence(**STRATEGIC_INTELLIGENCE)
        assert si.archetype == BrandArchetype.ARTISAN_MASTER
        assert si.archetype_confidence == 0.95
        assert len(si.power_words) == 15
        assert "cheap" in si.banned_phrases

    def test_entity_creation(self):
        e = Entity(entity="Amakusa clay", type=EntityType.MATERIAL, confidence=0.95)
        assert e.entity == "Amakusa clay"
        assert e.type == EntityType.MATERIAL

    def test_entity_confidence_range(self):
        with pytest.raises(Exception):
            Entity(entity="test", type=EntityType.MATERIAL, confidence=1.5)
        with pytest.raises(Exception):
            Entity(entity="test", type=EntityType.MATERIAL, confidence=-0.1)

    def test_entity_extraction_result(self):
        result = EntityExtractionResult(
            entities=[
                Entity(entity="Amakusa clay", type=EntityType.MATERIAL, confidence=0.95),
                Entity(entity="Arita", type=EntityType.REGION, confidence=0.99),
            ]
        )
        assert len(result.entities) == 2

    def test_entity_triplet_creation(self):
        t = EntityTriplet(
            subject="Our pottery",
            subject_type=EntityType.PRODUCT,
            relation="uses",
            object="Amakusa clay",
            object_type=EntityType.MATERIAL,
            confidence=0.9,
        )
        assert t.relation == "uses"

    def test_triplet_extraction_result(self):
        result = TripletExtractionResult(
            triplets=[
                EntityTriplet(
                    subject="Bowl",
                    subject_type=EntityType.PRODUCT,
                    relation="made_with",
                    object="Amakusa clay",
                    object_type=EntityType.MATERIAL,
                )
            ]
        )
        assert len(result.triplets) == 1


# =============================================================================
# Tests: System Prompts
# =============================================================================

class TestExtractionPrompts:
    """Verify extraction prompts contain expected instructions."""

    def test_strategic_audit_prompt_mentions_archetype(self):
        assert "archetype" in STRATEGIC_AUDIT_SYSTEM_PROMPT.lower()
        assert "artisan_master" in STRATEGIC_AUDIT_SYSTEM_PROMPT

    def test_strategic_audit_prompt_mentions_tonal_analysis(self):
        assert "tonal" in STRATEGIC_AUDIT_SYSTEM_PROMPT.lower()
        assert "formality" in STRATEGIC_AUDIT_SYSTEM_PROMPT.lower()

    def test_strategic_audit_prompt_mentions_power_words(self):
        assert "power words" in STRATEGIC_AUDIT_SYSTEM_PROMPT.lower()
        assert "banned" in STRATEGIC_AUDIT_SYSTEM_PROMPT.lower()

    def test_entity_prompt_lists_entity_types(self):
        assert "MATERIAL" in ENTITY_EXTRACTION_PROMPT
        assert "TECHNIQUE" in ENTITY_EXTRACTION_PROMPT
        assert "REGION" in ENTITY_EXTRACTION_PROMPT
        assert "PHILOSOPHY" in ENTITY_EXTRACTION_PROMPT

    def test_triplet_prompt_has_examples(self):
        assert "uses" in TRIPLET_EXTRACTION_PROMPT
        assert "originates_from" in TRIPLET_EXTRACTION_PROMPT


# =============================================================================
# Tests: IntelligenceExtractorService Methods
# =============================================================================

class TestIntelligenceExtractorService:
    """Test the service layer with mocked LLM."""

    @pytest.fixture
    def mock_llm(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_llm):
        return IntelligenceExtractorService(mock_llm)

    @pytest.mark.asyncio
    async def test_extract_strategic_audit_calls_llm(self, service, mock_llm):
        """extract_strategic_audit should call llm.generate_structured."""
        expected = StrategicIntelligence(**STRATEGIC_INTELLIGENCE)
        mock_llm.generate_structured = AsyncMock(return_value=expected)

        result = await service.extract_strategic_audit(BRAND_SOUL_RAW_TEXT)

        mock_llm.generate_structured.assert_called_once()
        call_kwargs = mock_llm.generate_structured.call_args.kwargs
        assert call_kwargs["response_format"] == StrategicIntelligence
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["temperature"] == 0.2
        assert "Takumi Ceramics" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_extract_strategic_audit_returns_pydantic_model(self, service, mock_llm):
        expected = StrategicIntelligence(**STRATEGIC_INTELLIGENCE)
        mock_llm.generate_structured = AsyncMock(return_value=expected)

        result = await service.extract_strategic_audit(BRAND_SOUL_RAW_TEXT)
        assert isinstance(result, StrategicIntelligence)
        assert result.archetype == BrandArchetype.ARTISAN_MASTER

    @pytest.mark.asyncio
    async def test_extract_strategic_audit_with_pillars(self, service, mock_llm):
        expected = StrategicIntelligence(**STRATEGIC_INTELLIGENCE)
        mock_llm.generate_structured = AsyncMock(return_value=expected)

        result = await service.extract_strategic_audit(
            BRAND_SOUL_RAW_TEXT,
            existing_pillars=["Heritage", "Craft"],
        )
        call_kwargs = mock_llm.generate_structured.call_args.kwargs
        assert "Heritage" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunk_calls_llm(self, service, mock_llm):
        entities = [
            Entity(entity="Amakusa clay", type=EntityType.MATERIAL, confidence=0.95),
            Entity(entity="Arita", type=EntityType.REGION, confidence=0.99),
        ]
        mock_llm.generate_structured = AsyncMock(
            return_value=EntityExtractionResult(entities=entities)
        )

        result = await service.extract_entities_from_chunk("We use Amakusa clay from Arita.")

        assert len(result) == 2
        assert result[0].entity == "Amakusa clay"
        call_kwargs = mock_llm.generate_structured.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"  # Cheaper model for entity extraction

    @pytest.mark.asyncio
    async def test_build_triplets_calls_llm(self, service, mock_llm):
        entities = [
            Entity(entity="Bowl", type=EntityType.PRODUCT, confidence=0.9),
            Entity(entity="Amakusa clay", type=EntityType.MATERIAL, confidence=0.95),
        ]
        triplets = [
            EntityTriplet(
                subject="Bowl",
                subject_type=EntityType.PRODUCT,
                relation="made_with",
                object="Amakusa clay",
                object_type=EntityType.MATERIAL,
                confidence=0.85,
            )
        ]
        mock_llm.generate_structured = AsyncMock(
            return_value=TripletExtractionResult(triplets=triplets)
        )

        result = await service.build_triplets(entities, source_text="A bowl made with Amakusa clay.")

        assert len(result) == 1
        assert result[0].subject == "Bowl"
        assert result[0].relation == "made_with"

    @pytest.mark.asyncio
    async def test_build_triplets_limits_entities(self, service, mock_llm):
        """Should limit entities to top 50 in the prompt."""
        many_entities = [
            Entity(entity=f"Entity{i}", type=EntityType.ATTRIBUTE, confidence=0.5)
            for i in range(100)
        ]
        mock_llm.generate_structured = AsyncMock(
            return_value=TripletExtractionResult(triplets=[])
        )

        await service.build_triplets(many_entities, source_text="text")

        call_kwargs = mock_llm.generate_structured.call_args.kwargs
        # Prompt should contain at most 50 entity lines
        entity_lines = [l for l in call_kwargs["prompt"].split("\n") if l.strip().startswith("- ")]
        assert len(entity_lines) <= 50

    @pytest.mark.asyncio
    async def test_build_triplets_limits_source_text(self, service, mock_llm):
        """Should limit source text to 3000 chars."""
        long_text = "a" * 10000
        mock_llm.generate_structured = AsyncMock(
            return_value=TripletExtractionResult(triplets=[])
        )
        entities = [Entity(entity="Test", type=EntityType.ATTRIBUTE, confidence=0.5)]

        await service.build_triplets(entities, source_text=long_text)

        call_kwargs = mock_llm.generate_structured.call_args.kwargs
        # The source text in prompt should be truncated
        assert len(call_kwargs["prompt"]) < 10000
