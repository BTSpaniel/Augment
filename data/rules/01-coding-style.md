# Coding style & comment policy

Augment writes code that another human can audit cold. That means
every new file ships with a header banner, every section gets a
comment marker, and every public function has a docstring. The
loaders in `augment.context.rules_store` pick this file up
automatically — no restart needed when you edit it.

## File-header banner (required for every new file)

A 4-12 line block at the top of the file naming:

1. The file's single-line purpose.
2. The major sections it contains.
3. Anything load-bearing the next reader must know (gotchas, ports,
   ownership, "do not edit by hand", etc.).

Python:

```python
"""Provider context-window resolver.

Three-tier: explicit config override -> live provider introspection ->
static catalog -> conservative fallback. Adapters live further down.
"""
```

HTML:

```html
<!--
  Single-file birthday cake page.
  Sections (in order): Header, Hero, Stats, Feature 01..04, Footer.
  Inline CSS at the top of <head>, all JS at the bottom of <body>.
-->
```

JS / CSS:

```js
/**
 * Fullscreen WebGPU particle background with text-avoidance.
 *
 * Sections (in order): bgStart bootstrap, resize handler, frame loop,
 * substance shaders (water/fire/acid/plasma/sand/steam/oil).
 */
```

## Section comments (every file >100 lines)

Pick the marker that matches the language, and use it consistently:

| Language | Marker style                          |
|----------|---------------------------------------|
| Python   | `# -- Section name --------------`    |
| JS / CSS | `/* -- Section name -------------- */`|
| HTML     | `<!-- Section name -->`               |
| Bash     | `# == Section name ============`      |

Examples that match the conventions of this repo's screenshots:

```html
<!-- Header -->
<div class="header">...

<!-- Stats -->
<section class="stats-section">...

<!-- Feature 01: Virtual GPU -->
<div class="feature-section reveal">...
```

```js
// ============================================
// Fullscreen WebGPU particle background
// ============================================
async function bgStart() { ... }

// Substance IDs: 0=water 1=fire 2=acid 3=plasma 4=sand 5=steam 6=oil
// Particle layout: pos.xy=position, pos.z=life, pos.w=substance(0-6)
const csCode = `...`;
```

## Docstrings (every public function/class)

The first line is a one-line summary written in the imperative
("Resolve the active context window", not "Resolves..."). For
non-trivial functions, follow with a blank line and a doc block
explaining intent, side effects, and any non-obvious arguments.

```python
def resolve_context_window(profile, *, allow_introspection=True):
    """Resolve the active context window for ``profile``.

    Three-tier resolution: explicit override -> live introspection
    (OpenRouter / Groq / Ollama / LM Studio / llama.cpp) -> static
    catalog by model id. Falls back to 32k tokens.

    Args:
        profile: Provider profile dict.
        allow_introspection: Set False in tests / offline use.
    """
```

## Inline comments — WHY, never WHAT

The code already says WHAT. Comments belong on the lines where the
reader will pause and ask "wait, why is it doing it that way?".

Bad:

```python
# Increment counter
counter += 1
```

Good:

```python
# OpenAI streams tool_calls as a series of partial deltas keyed by
# index — merge by index rather than by id so we don't drop the
# first chunk before id arrives.
tool_calls_by_index[idx] = merged
```

## Naming

- Python: `snake_case` for functions/vars/modules, `PascalCase` for
  classes, `SCREAMING_SNAKE` for module-level constants.
- JS: `camelCase` for functions/vars, `PascalCase` for classes/
  components, `SCREAMING_SNAKE` for module-level constants.
- File names: `kebab-case.html`, `snake_case.py`, `kebab-case.css`,
  `camelCase.js` (only because the existing UI files do).

## Imports / top-of-file

- Group order: stdlib -> third-party -> first-party. Blank line
  between groups.
- Avoid `from x import *`.
- Local imports (inside a function body) are OK when they break
  import cycles or are expensive; comment why.

## Anti-patterns to avoid

- "TODO" without an owner or date. Either fix it or leave a precise
  note with the path of the missing piece.
- Multi-paragraph blocks of comments that paraphrase the code line
  by line.
- "magic numbers" — bind them to a constant with a comment.
- Functions longer than ~60 lines without a section comment dividing
  them; split the body.
- Test files with no docstring on the test function — the docstring
  IS the assertion of intent.
