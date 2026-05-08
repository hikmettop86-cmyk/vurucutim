"""Move {{ dna_css|safe }} to the END of <style> block in templates where it
was placed BEFORE :root (causing template defaults to override user palette).

For each affected template:
  - Remove the early dna_css line
  - Insert it just before </style>
"""
import re
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / 'templates'
DNA_LINE = '{{ dna_css|safe }}'


def fix(path: Path) -> bool:
    text = path.read_text(encoding='utf-8')
    if DNA_LINE not in text:
        return False

    dna_idx = text.find(DNA_LINE)
    root_idx = text.find(':root')
    if root_idx == -1 or dna_idx > root_idx:
        return False  # already correct

    # Remove the line containing dna_css (with surrounding newlines)
    line_start = text.rfind('\n', 0, dna_idx) + 1
    line_end = text.find('\n', dna_idx) + 1
    removed_line = text[line_start:line_end]

    text_without = text[:line_start] + text[line_end:]

    # Insert before </style>
    style_close = text_without.find('</style>')
    if style_close == -1:
        return False

    # Indent to match
    insert = '  /* DNA OVERRIDE — runtime palette/font from channel DNA */\n  ' + DNA_LINE + '\n'
    new_text = text_without[:style_close] + insert + text_without[style_close:]

    path.write_text(new_text, encoding='utf-8')
    return True


if __name__ == '__main__':
    for tmpl in sorted(TEMPLATE_DIR.glob('*.html.j2')):
        if fix(tmpl):
            print(f"✓ {tmpl.name} — dna_css moved to end of <style>")
        else:
            print(f"  {tmpl.name} — no change")
