"""Replace hardcoded hex colors in templates with their :root CSS variable.

For each template/*.html.j2:
  1. Parse :root { --name: #hex; ... }
  2. In the rest of the file, replace standalone occurrences of those hex
     values (lowercased) with var(--name).

This makes runtime palette overrides (text_main, primary, accent, etc) actually
flow through to all elements, instead of being shadowed by hardcoded defaults.
"""
import re
import sys
from pathlib import Path


HEX6 = re.compile(r'#[0-9a-fA-F]{6}\b')


def fix_template(path: Path) -> tuple[bool, list[str]]:
    text = path.read_text(encoding='utf-8')

    # Find :root block (use first occurrence)
    root_match = re.search(r':root\s*\{([^}]+)\}', text, re.DOTALL)
    if not root_match:
        return False, []

    root_block = root_match.group(1)

    # Parse CSS vars whose value is a single hex color
    hex_to_var: dict[str, str] = {}
    for m in re.finditer(r'--([A-Za-z0-9_-]+)\s*:\s*([^;]+);', root_block):
        name = m.group(1).strip()
        value = m.group(2).strip()
        m2 = re.match(r'^(#[0-9a-fA-F]{6})$', value)
        if m2:
            hex_to_var[m2.group(1).lower()] = name

    if not hex_to_var:
        return False, []

    # Operate only on text AFTER :root block (preserve :root defaults)
    before = text[:root_match.end()]
    after = text[root_match.end():]

    replaced = []

    def replacer(m: re.Match) -> str:
        hex_value = m.group(0).lower()
        if hex_value in hex_to_var:
            var_name = hex_to_var[hex_value]
            replaced.append(f'{hex_value} -> var(--{var_name})')
            return f'var(--{var_name})'
        return m.group(0)

    new_after = HEX6.sub(replacer, after)

    if new_after == after:
        return False, []

    path.write_text(before + new_after, encoding='utf-8')
    return True, replaced


def main():
    root = Path(__file__).resolve().parent.parent
    template_dir = root / 'templates'
    if not template_dir.is_dir():
        print(f"ERROR: {template_dir} bulunamadı")
        sys.exit(1)

    total = 0
    for tmpl in sorted(template_dir.glob('*.html.j2')):
        changed, replacements = fix_template(tmpl)
        if changed:
            total += len(replacements)
            print(f"\n✓ {tmpl.name} ({len(replacements)} replacement)")
            for r in replacements[:8]:
                print(f"    {r}")
            if len(replacements) > 8:
                print(f"    ... +{len(replacements) - 8} more")
        else:
            print(f"  {tmpl.name} (no changes)")

    print(f"\nTotal: {total} hardcoded hex colors replaced with var()")


if __name__ == '__main__':
    main()
