"""Keep visible web sections separate; never infer names missing from a page."""
import re


def web_sections(content):
    """Split at explicit Markdown/Chinese outline headings, preserving raw text.

    No heading is manufactured and no hidden part of the 6000-character model
    excerpt is used. Numbered audience groups are independent evidence scopes.
    """
    headings = []
    for match in re.finditer(r'^.*$', content, flags=re.M):
        line = match.group().strip()
        plain = line.strip('* ').strip()
        numbered = re.match(r'^[一二三四五六七八九十]+[、．.]\s*\S', plain)
        markdown = re.match(r'^(#{1,6})\s+(.+)', line)
        if numbered or markdown:
            title = markdown.group(2).strip('* ') if markdown else plain
            level = len(markdown.group(1)) if markdown else 2
            headings.append((match.start(), level, title))
    if not headings:
        return [{'content': content, 'section_path': []}]
    sections, path = [], []
    if content[:headings[0][0]].strip():
        sections.append({'content': content[:headings[0][0]], 'section_path': []})
    for index, (start, level, title) in enumerate(headings):
        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, title))
        end = headings[index+1][0] if index+1 < len(headings) else len(content)
        sections.append({'content': content[start:end], 'section_path': [p[1] for p in path]})
    return sections
