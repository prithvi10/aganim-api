import json
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.main.utils.llm_parser import parse_llm_json, recover_title_desc

def test_parsing():
    scenarios = [
        {
            "name": "Fenced JSON",
            "input": '```json\n{"title": "Luxury Kimono", "description": "<div>Silk</div>"}\n```',
            "expected": "Luxury Kimono"
        },
        {
            "name": "Malformed with Prose",
            "input": "Here is the title: 'Prose Title' and the description is 'Some HTML here' }",
            "expected": "Prose Title"
        }
    ]

    print("=== Testing LLM Parsing Logic ===\n")
    for s in scenarios:
        print(f"Scenario: {s['name']}")
        result = parse_llm_json(s['input'])
        if not result:
            result = recover_title_desc(s['input'])
        
        if result and result.get("title") == s['expected']:
            print(f"  ✅ SUCCESS: {result['title']}")
        else:
            print(f"  ❌ FAILURE: Got {result}")

if __name__ == "__main__":
    test_parsing()

