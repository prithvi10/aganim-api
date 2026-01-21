import pytest
from src.main.utils.llm_parser import parse_llm_json, recover_title_desc

def test_parse_llm_json_clean():
    raw = '{"title": "Test", "description": "Desc"}'
    assert parse_llm_json(raw) == {"title": "Test", "description": "Desc"}

def test_parse_llm_json_markdown():
    raw = '```json\n{"title": "Test", "description": "Desc"}\n```'
    assert parse_llm_json(raw) == {"title": "Test", "description": "Desc"}

def test_parse_llm_json_surrounding_text():
    raw = 'Some text before {"title": "Test", "description": "Desc"} and after'
    assert parse_llm_json(raw) == {"title": "Test", "description": "Desc"}

def test_recover_title_desc_success():
    raw = 'The title is "My Title" and description: "My Desc" seo_alt_text: "Black leather wallet - slim design"'
    recovered = recover_title_desc(raw)
    assert recovered["title"] == "My Title"
    assert recovered["description"] == "My Desc"
    assert recovered["seo_alt_text"] == "Black leather wallet - slim design"

def test_recover_title_desc_partial():
    raw = 'Just the title is "Only Title"'
    recovered = recover_title_desc(raw)
    assert recovered["title"] == "Only Title"
    assert recovered["description"] == raw

def test_recover_title_desc_none():
    raw = 'No matches here'
    assert recover_title_desc(raw) is None

