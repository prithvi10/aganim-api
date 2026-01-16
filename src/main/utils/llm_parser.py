import json
import re
import ast

def parse_llm_json(raw_content: str) -> dict | None:
    """
    Robust JSON parsing for LLM output, handling markdown fences and surrounding text.
    """
    cleaned = raw_content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]

    try:
        return json.loads(cleaned.strip())
    except Exception:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            # Try common repairs: remove trailing commas, then attempt ast.literal_eval for single-quote dicts.
            try:
                repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
                return json.loads(repaired)
            except Exception:
                pass
            try:
                # Convert JSON literals to Python for literal_eval
                pyish = re.sub(r"\bnull\b", "None", candidate)
                pyish = re.sub(r"\btrue\b", "True", pyish, flags=re.IGNORECASE)
                pyish = re.sub(r"\bfalse\b", "False", pyish, flags=re.IGNORECASE)
                obj = ast.literal_eval(pyish)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass
    return None


def recover_title_desc(raw_content: str) -> dict | None:
    """
    Last-resort extractor to pull "title" and "description" from semi-structured text
    even if full JSON parse fails. Returns None if both are missing.
    """
    # More flexible regex for keys: optional quotes, optional colon/is/=
    title_match = re.search(r'["\']?title["\']?\s*(?:[:=]|is)\s*["\']([^"\']+)["\']', raw_content, re.IGNORECASE)
    desc_match = re.search(r'["\']?description["\']?\s*(?:[:=]|is)\s*["\'](.+)', raw_content, re.IGNORECASE | re.DOTALL)
    seo_title_match = re.search(r'["\']?seo_title["\']?\s*(?:[:=]|is)\s*["\']([^"\']+)["\']', raw_content, re.IGNORECASE)
    seo_desc_match = re.search(r'["\']?seo_description["\']?\s*(?:[:=]|is)\s*["\']([^"\']+)["\']', raw_content, re.IGNORECASE)

    title = title_match.group(1).strip() if title_match else None
    seo_title = seo_title_match.group(1).strip() if seo_title_match else ""
    seo_description = seo_desc_match.group(1).strip() if seo_desc_match else ""
    description = None
    if desc_match:
        description = desc_match.group(1).strip()
        # Simple cleanup for common trailing junk
        for suffix in ['"', "'", "}", "```", "  "]:
            if description.endswith(suffix):
                description = description.rstrip(suffix).strip()
    
    if title or description:
        return {
            "title": title or "Generated Copy",
            "description": description or raw_content,
            "seo_title": seo_title,
            "seo_description": seo_description,
        }
    return None

