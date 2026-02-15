import re


def detect_and_label_sections(text: str) -> str:
    """
    Detect common Japanese section headers and wrap them with explicit [Section: <Label>] ... [/Section] tags.
    This helps the LLM preserve the original divisions and order.
    """
    lines = text.splitlines()
    labeled_lines = []

    header_patterns = [
        re.compile(r"^【(?P<label>[^】]+)】"),
        re.compile(r"^(?P<label>.+?)[：:]"),
        re.compile(r"^(?P<label>.+?)[?？]$"),
    ]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            labeled_lines.append(line)
            continue

        label_found = None
        for pattern in header_patterns:
            m = pattern.match(stripped)
            if m:
                label_found = m.group("label").strip()
                break

        if label_found:
            labeled_lines.append(f"[Section: {label_found}] {stripped} [/Section]")
        else:
            labeled_lines.append(line)

    return "\n".join(labeled_lines)
