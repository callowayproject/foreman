---
name: Foreman
description: An always-on AI co-maintainer for your GitHub repositories.
colors:
  blueprint-steel: "#43527A"
  pre-dawn-navy: "#172A54"
  safety-tape-pale: "#FDF396"
  site-signal-amber: "#F7B526"
  construction-orange: "#FE6400"
typography:
  headline:
    fontFamily: "Roboto, system-ui, -apple-system, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.334
    letterSpacing: "normal"
  body:
    fontFamily: "Roboto, system-ui, -apple-system, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  label:
    fontFamily: "Roboto, system-ui, -apple-system, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.75
    letterSpacing: "0.02857em"
rounded:
  sm: "4px"
  md: "8px"
  pill: "100px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  card:
    backgroundColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "{spacing.md}"
  card-header:
    backgroundColor: "{colors.blueprint-steel}"
    textColor: "#ffffff"
    padding: "16px 16px 24px"
  tag:
    backgroundColor: "rgba(0, 0, 0, 0.08)"
    textColor: "{colors.pre-dawn-navy}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  doc-label:
    backgroundColor: "{colors.blueprint-steel}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
    padding: "0 5px"
---

# Design System: Foreman

## 1. Overview

### Creative North Star: "The Infrastructure Manual"

This is documentation built the way a foreman runs a job site: precise, no wasted motion,
and trustworthy on day one and day five hundred.
The visual system earns credibility through restraint.
A developer who lands on these docs is skeptical by default —
they've been burned by tools with slick marketing that delivered nothing.
Foreman's design answers that skepticism by refusing to perform.
No animated hero numbers, no gradient blobs, no "10x your workflow" copy.
Just dense, correct, structured information that says: this was built by people who use tools like this.

The reference is the kind of documentation engineers save as a bookmark and actually return to:
Docker Compose reference, the GNU Make manual, Stripe's API docs.
These are trusted not because they look expensive, but because they have exactly what you need and nothing you don't.
Color is used for orientation, not decoration.
Typography is functional, not expressive.
Every component earns its place by doing a job.

This system is explicitly not an AI startup landing page.
No glassmorphism, no hero metrics, no gradient text, no friendly onboarding flows.
The people who need Foreman already know they need it.
The design's job is to get out of the way and prove the tool with information.

### Key Characteristics

- Flat surfaces: depth through tonal color difference and 1px borders, never shadows
- Construction-site palette: anchored in physical-world signaling colors
- Weight-driven type hierarchy: scale and weight contrast, no decorative typefaces
- Components that document, not decorate

## 2. Colors: The Worksite Palette

The palette draws from a physical job site.
Deep navy frames the structure, amber signals waypoints, and one vivid orange marks action —
the way a hard hat orange does.

### Primary

- **Blueprint Steel** (`#43527A` / `hsl(224, 29%, 37%)`): The workhorse color.
    Used for the navigation header, card headers, active states, and links.
    Medium slate-blue — calm, authoritative, legible against white.
    Not vibrant enough to feel "AI startup blue."
- **Pre-Dawn Navy** (`#172A54` / `hsl(221, 57%, 21%)`): The darkest brand tone.
    Used for deep backgrounds, heavy text contexts, and the logo mark.
    Its intensity signals depth and seriousness.

### Secondary

- **Site Signal Amber** (`#F7B526` / `hsl(41, 93%, 56%)`): The accent.
    Used for interactive highlights, hover states, and emphasis marks.
    Warm and high-contrast against navy — the equivalent of a fluorescent safety marker.
- **Construction Orange** (`#FE6400`): The logo's action color.
    Reserved for primary CTAs and the most important interactive actions on a page.
    Use sparingly: its rarity is the point.

### Tertiary

- **Safety Tape Pale** (`#FDF396` / `hsl(54, 96%, 79%)`): A pale, almost-neutral lemon-yellow.
    Used at very low opacity as a surface tint (sidebar background wash).
    Never as a foreground or text color — it reads as highlight, not content.

### Neutral

- **Near-Black** (inherited from Material theme — target `hsl(221, 15%, 10%)`): Tint text toward the brand hue.
    Pure `#000000` is forbidden.
- **Surface whites and off-whites**: Material theme defaults.
    Card bodies are white; the sidebar receives the Safety Tape Pale wash at 7% opacity (`--light-gold--lightest`).

### Named Rules

**The One Orange Rule.**
Construction Orange appears on one primary action per screen.
Its rarity is the point.
When everything is orange, nothing is urgent.

**The Blue-Not-Indigo Correction.**
The Material theme's `--md-primary-fg-color--light` (`#ECB7B7`)
and `--md-primary-fg-color--dark` (`#90030C`) are off-brand carryover defaults.
Replace both with tints and shades derived from Blueprint Steel, not from unrelated red/pink values.

## 3. Typography

**Body Font:** Roboto (with `system-ui, -apple-system, sans-serif` fallback) **Label/Mono Font:** System monospace stack
for code samples

**Character:** A single neutral sans-serif family.
No display font.
The decision is deliberate: Foreman's documentation is a reference, not a brand expression.
Typography serves legibility and hierarchy — the words carry the voice, not the typeface.

### Hierarchy

- **Headline** (700 weight, 1.5rem, lh 1.334): Section and page titles.
    The primary visual anchor on any doc page.
- **Body** (400 weight, 1rem, lh 1.6): All prose content.
    Max line length 70ch.
    Wider than that and the reader loses the line.
- **Label** (500 weight, 0.8125rem, lh 1.75, ls 0.029em): Card subtitles, meta text, tag labels,
    navigation secondary text.
    Slightly tracked for legibility at small size.
- **Code** (system-ui-monospace, 0.875rem): Inline code and code blocks.
    Distinguishable from prose at a glance.

### Named Rules

**The Single-Family Rule.** One typeface.
Different weights and sizes, not different families.
Mixing a display serif into developer docs reads as a design decision made by someone who doesn't use the docs.

## 4. Elevation

This system is flat by default.
No `box-shadow` except browser-native focus rings (which must never be removed).
Depth is expressed through two mechanisms only:

1. **Tonal layering**: a surface that needs separation gets a different background color —
    typically the Safety Tape Pale wash at 4–8% opacity, or a shift from white to `--md-default-bg-color--light`.
2. **1px borders**: when tonal difference alone isn't enough to separate an element,
    a single 1px border in a muted tone provides the edge.
    Use `rgba(0, 0, 0, 0.12)` or a Blueprint Steel tint at 20% opacity.

Cards do not use Material's three-layer `box-shadow`.
Replace it with a `1px solid rgba(67, 82, 122, 0.2)` border.

**The Flat-First Rule.**
If you're reaching for `box-shadow`, try a border or background-color shift first.
Shadows communicate that an element is physically lifted — which implies interactivity or importance.
Use that signal only when it's true.

## 5. Components

### Navigation

The Material header carries Blueprint Steel (`#43527A`) as its background.
Navigation links are white at rest, Site Signal Amber on hover and active state.
No underlines on hover — the color change is sufficient signal.
The sidebar receives the Safety Tape Pale wash at 7% opacity,
giving it a distinct but subtle identity without needing a border.

### Cards

- **Corner Style:** Gently rounded (4px radius — `{rounded.sm}`)
- **Background:** White body; Blueprint Steel header
- **Shadow Strategy:** None.
    A single `1px solid rgba(67, 82, 122, 0.2)` border replaces the Material box-shadow.
- **Header Padding:** 16px 16px 24px (extra bottom space for the header-to-content transition)
- **Content Padding:** 16px on all sides
- **Card Header Title:** 700 weight, 1.14em — the primary information landmark in the card

### Tags / Chips

- **Style:** Pill shape (`{rounded.pill}`), muted background (`rgba(0,0,0,0.08)`), Pre-Dawn Navy text
- **Size:** 24px height, `{spacing.xs} {spacing.sm}` padding, label-weight type
- **Usage:** Read-only descriptors only.
    Not interactive unless the design explicitly requires it.
    Interactive tags get a Blueprint Steel border.

### API Doc Labels

- **Style:** Pill shape (`{rounded.pill}`), Blueprint Steel background, white text
- **Variants:** `private` (muted red), `property` (muted green), `read-only` (muted yellow).
    Exact colors defined in `extra.css`.
- **Size:** Small (fits inline with body text).
    Label-weight type, no letter-spacing.

### Navigation (Sidebar)

- **Default state:** Body text weight, no background
- **Active/current state:** Blueprint Steel text, 500 weight — no left-border accent stripe
- **Hover:** Site Signal Amber text

**The No-Stripe Rule.**
No `border-left` accent stripe on sidebar items, list items, or callouts.
Ever.
A colored left border is decorative affectation.
Use background tint or text color for active state.

## 6. Do's and Don'ts

### Do

- **Do** use Blueprint Steel for primary navigation, card headers, and active states — it is the load-bearing color.
- **Do** express depth through tonal background shifts and 1px borders instead of `box-shadow`.
- **Do** cap body prose at 70ch line length for legibility.
- **Do** use Construction Orange for one primary action per page — its scarcity signals importance.
- **Do** use Site Signal Amber for hover and active interactive states across the site.
- **Do** keep the sidebar tinted with Safety Tape Pale at 7% opacity —
    it visually anchors the navigation zone without adding weight.
- **Do** maintain a minimum 4.5:1 contrast ratio on all text (WCAG AA).

### Don't

- **Don't** use gradient text (`background-clip: text`).
    Never intentional.
    Use a solid color.
- **Don't** use glassmorphism: blur backgrounds, frosted cards, backdrop-filter as decoration.
- **Don't** use hero metrics: big number, small label, gradient accent.
    This is an AI startup cliché and it's prohibited.
- **Don't** use animated counters, scroll-triggered number tickers, or decorative entrance animations.
- **Don't** use a `border-left` greater than 1px as a colored accent stripe on any element.
- **Don't** use gradient blob backgrounds, mesh gradients, or radial color washes behind content.
- **Don't** use `#000000` or `#ffffff` as literal color values.
    Tint every neutral toward the brand hue.
- **Don't** add Material's three-layer `box-shadow` to new components.
    The shadow says "lifted and interactive"; flat says "structural and trusted."
- **Don't** write hero copy that makes promises about productivity ("10x", "streamline", "supercharge").
    State what Foreman does, not what it will do for your feelings.
- **Don't** use the off-brand Material defaults `#ECB7B7` and `#90030C`.
    Replace them with Blueprint Steel tints and shades.
