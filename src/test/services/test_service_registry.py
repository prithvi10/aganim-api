"""
Unit tests for ServiceRegistry.

Tests factory methods and service initialization.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.main.services.registry import ServiceRegistry


# =============================================================================
# Tests: Factory Methods
# =============================================================================

def test_create_default_initializes_all_services():
    """Test that create_default initializes all services."""
    with patch.dict('os.environ', {
        'OPENAI_API_KEY': 'test-openai-key',
        'SERP_API_KEY': 'test-serp-key',
    }):
        registry = ServiceRegistry.create_default()
        
        # Should have all services
        assert registry.llm is not None
        assert registry.serp is not None
        assert registry.rag is not None


def test_create_default_with_missing_keys():
    """Test that create_default handles missing API keys gracefully."""
    with patch.dict('os.environ', {}, clear=True):
        # Should not raise, but services may be None
        registry = ServiceRegistry.create_default()
        
        # Registry should still be created
        assert registry is not None


def test_create_for_testing():
    """Test that create_for_testing creates mock services."""
    registry = ServiceRegistry.create_for_testing()
    
    # Should have mock services
    assert registry.llm is not None
    assert registry.serp is not None
    assert registry.rag is not None


def test_create_for_testing_with_custom_mocks():
    """Test that create_for_testing accepts custom mocks."""
    custom_llm = MagicMock()
    custom_serp = MagicMock()
    
    registry = ServiceRegistry.create_for_testing(
        llm=custom_llm,
        serp=custom_serp,
    )
    
    assert registry.llm is custom_llm
    assert registry.serp is custom_serp


# =============================================================================
# Tests: Attribute Access
# =============================================================================

def test_registry_attributes():
    """Test that registry provides expected attributes."""
    registry = ServiceRegistry.create_for_testing()
    
    # Check attributes exist
    assert hasattr(registry, 'llm')
    assert hasattr(registry, 'serp')
    assert hasattr(registry, 'rag')


# =============================================================================
# Tests: Integration with Agents
# =============================================================================

def test_registry_compatible_with_agents():
    """Test that registry can be used with agents."""
    from src.main.agents.copywriter import CopywriterAgent
    
    registry = ServiceRegistry.create_for_testing()
    
    # Should be able to create agent with registry
    agent = CopywriterAgent("test-shop.myshopify.com", registry)
    
    assert agent.services is registry
