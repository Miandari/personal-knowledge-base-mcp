"""Markdown section extraction and splicing for section-protected compilation."""

import re


def extract_section(md: str, heading: str) -> str:
    """Extract content of a ## heading section.

    Returns the content between ## heading and the next ## heading (or EOF).
    Returns empty string if the section doesn't exist.
    """
    pattern = rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    m = re.search(pattern, md, re.MULTILINE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def replace_or_insert_section(
    md: str,
    heading: str,
    content: str,
    before: str = "Notes",
) -> str:
    """Replace ## heading content, or insert before ## before_heading if absent.

    If neither the target section nor the before section exist,
    appends at the end of the document.

    The content should NOT include the ## heading itself — it will be added.
    If content accidentally starts with the heading, it's stripped.
    """
    # Strip duplicate heading from content if LLM included it
    content = content.strip()
    heading_line = f"## {heading}"
    if content.startswith(heading_line):
        content = content[len(heading_line):].strip()

    section_block = f"## {heading}\n\n{content}\n\n"

    # Try to replace existing section
    pattern = rf"^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)"
    if re.search(pattern, md, re.MULTILINE | re.DOTALL):
        return re.sub(pattern, section_block, md, count=1, flags=re.MULTILINE | re.DOTALL)

    # Insert before the target section
    before_pattern = rf"^## {re.escape(before)}\s*\n"
    m = re.search(before_pattern, md, re.MULTILINE)
    if m:
        return md[:m.start()] + section_block + md[m.start():]

    # Fallback: append after the title (first # heading + its paragraph)
    title_pattern = r"^# .+\n\n?"
    m = re.search(title_pattern, md, re.MULTILINE)
    if m:
        return md[:m.end()] + "\n" + section_block + md[m.end():]

    # Last resort: append to end
    return md.rstrip() + "\n\n" + section_block


def normalize_alias(raw: str) -> str:
    """Normalize an alias for consistent lookup.

    Path segments are preserved so that legacy old_path aliases
    (e.g., concepts/cache vs sources/cache) remain distinguishable.
    """
    s = raw.strip().lower()
    s = s.replace("[[", "").replace("]]", "")
    s = s.replace(" ", "-")
    s = s.strip("/")
    return s
