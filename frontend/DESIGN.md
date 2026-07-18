# Corpus Frontend — Gemini Design Language

Design system for the React frontend, derived from Google's Gemini visual design
(design.google/library/gemini-ai-visual-design). Tokens live in
`src/styles/index.css` as CSS custom properties, themed via `data-theme` on `<html>`.

## Principles

- **Gradients are context builders** — they convey energy and directional momentum,
  never decoration. The signature gradient has a sharp blue leading edge that
  diffuses toward a transparent tail.
- **Circles convey simplicity, harmony, comfort** — pill inputs, round chips,
  circular avatars, 24px card radii.
- **Motion is functional** — shimmer means "thinking", ripple means "sent",
  stagger-reveal means "reasoning steps arriving". Nothing animates without meaning.
  `prefers-reduced-motion` disables all of it.
- **Soft and direct** — ethereal blurred gradient blobs behind the greeting;
  crisp typography and dense information everywhere else.

## Tokens

### Signature gradient
```css
--gradient-gemini: linear-gradient(74deg, #4285F4 0%, #9B72CB 35%, #D96570 60%, transparent 100%);
--gradient-gemini-solid: linear-gradient(74deg, #4285F4 0%, #9B72CB 50%, #D96570 100%);
```
Used for: greeting headline (`background-clip: text`), thinking shimmer, send button,
citation chips, assistant avatar, active trace dot.

### Four-color accents (sparingly)
| Token | Value | Use |
|---|---|---|
| `--g-blue` | `#4285F4` | primary accent, category chips |
| `--g-red` | `#EA4335` | errors, thumbs-down |
| `--g-yellow` | `#FBBC04` | warnings |
| `--g-green` | `#34A853` | health, indexed status, thumbs-up |

### Surfaces
| Token | Light | Dark |
|---|---|---|
| `--bg` | `#FFFFFF` | `#131314` |
| `--surface` | `#F0F4F9` | `#1E1F20` |
| `--surface-2` | `#E9EEF6` | `#282A2C` |
| `--surface-3` | `#DDE3EA` | `#333537` |
| `--text` | `#1F1F1F` | `#E3E3E3` |
| `--accent` | `#0B57D0` | `#A8C7FA` |
| `--accent-soft` | `#D3E3FD` | `#0842A0` |

### Shape
- Prompt bar: full pill (`9999px`), relaxes to `28px` when multiline
- Cards: `24px` · Chips: `16px` · Everything interactive is rounded

### Type
- Display/greeting: **Outfit** (geometric, Product-Sans-like)
- Body/UI: **Inter Variable**
- Scale: 40 / 28 / 16 / 14 / 12; greeting is gradient-clipped text

### Motion
- Easing: `cubic-bezier(0.2, 0.8, 0.2, 1)` everywhere
- Thinking shimmer: 1.8s linear gradient sweep across text
- Trace steps: stagger-fade at 0.08s intervals (framer-motion)
- Send: radial ripple, 700ms
- Hover cards: `-translate-y-0.5` + shadow
