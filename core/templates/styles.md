# NewsCard Studio — 20-style prompt library

Each section is a self-contained art direction for one 1080×1350 news card.
Only the selected section is sent to the design model. Edit any section freely;
the dashboard reads the names from `core/design.py`, so keep the `## Style N — Name`
heading format if you change a name (or update the matching list).

## Style 1 — Quiet Broadsheet

A calm, premium newspaper page for a reader who saves cards. Warm ivory background
(#F5F1E8), near-black ink (#141414), one muted accent (use the brand accent at 55%
strength). Typography: Fraunces for the headline, 84–104px, tight leading; a small
uppercase sans eyebrow for the category with wide tracking. Layout: generous 72px
padding, a hairline rule above the category, photo cropped to a tall portrait panel
on the right third with a thin inner border, text stacked left. Keep the photo quiet
with a warm overlay (opacity 0.08). Signature detail: a tiny issue number and date
in the footer. No icons, no gradients.

## Style 2 — Midnight Terminal

A late-night technology desk with the confidence of a terminal window, but readable.
Background #0D1117, text #E6EDF3, accent mint (#74F2B5) used sparingly for labels
and a 2px rule. Typography: IBM Plex Mono for the category and metadata, Space Grotesk
bold for a 78–92px headline. Layout: full-bleed darkened photo across the top 58%,
a fine scanline texture at 3% opacity, then copy on a solid dark panel. Add a small
"signal / 01" label. Signature detail: a blinking-cursor style vertical bar after the
headline (static, no animation). Keep every line high contrast.

## Style 3 — Soft Editorial

A gentle Sunday magazine mood. Background in a pale tint of the brand accent mixed
with white; text #1B1B1B. Typography: Instrument Serif for an elegant 88–102px
headline, Work Sans for body and labels. Layout: large rounded photo (28px radius)
occupying the upper half, headline overlapping the photo's lower edge on a cream
panel with generous padding. Signature detail: a small circular badge with the
category initial in the corner. Soft, no shadows; use spacing instead of borders.

## Style 4 — Bold Poster

A street-poster composition built to stop a thumb. Background in a saturated brand
pastel; oversized black type; one solid photo block. Typography: Archivo Black or
Bebas Neue for the headline at 120–148px, uppercase, tight tracking. Layout: photo
as a hard-edged rectangle on the lower 45%, headline in the upper half with manual
line breaks, description in a small box with a 2px border. Signature detail: a
repeating diagonal tick pattern in one corner at 8% opacity. High contrast, no
gradients, no rounded corners except the card edge.

## Style 5 — Newsprint Classic

A front-page feel with honest texture. Background #F2EFE6 with a faint paper-grain
overlay, black ink, no accent except a 1px deep red rule (or the brand accent).
Typography: Playfair Display for a 92–108px headline; Libre Franklin for a deck,
byline and source. Layout: a masthead-like brand name across the top with a double
rule, photo in a wide landscape crop below it, headline beneath, description as a
short deck. Signature detail: a small "EXCLUSIVE / DAILY BRIEF" stamp in outline.
Keep everything aligned to a strict 12-column grid.

## Style 6 — Swiss Grid

International-style order: white background, black type, one red-orange accent
(or the brand accent), ruthless alignment. Typography: Helvetica-like sans (Inter),
headline 76–92px, medium weight, left aligned; category in 12px uppercase with
tracking. Layout: asymmetric grid — headline in the left 60%, a square photo block
top-right, description bottom-left, metadata vertical on the far right edge. Signature
detail: thin 1px grid lines that almost disappear. No decoration, no curves.

## Style 7 — Monochrome Minimal

A gallery caption for serious news. Off-white #FAFAF8 background, charcoal #1A1A1A
text, photo treated in black and white with a slight contrast lift (CSS filter
grayscale). Typography: DM Serif Display for the headline at 84–96px; Inter for all
supporting text. Layout: photo as a tall central column with wide margins, headline
below, category as a small outlined pill, description two lines. Signature detail:
a hairline vertical line down the left margin with the date rotated 90°. Quiet and
confident.

## Style 8 — Magazine Cover

A cover that feels like it belongs on a shelf. Full-bleed photo with a dark bottom
scrim; cover lines in cream. Typography: Syne bold for a 96–120px headline, uppercase;
Playfair Display italic for a short kicker; tiny sans for the cover lines. Layout:
brand wordmark top-left, category top-right, headline placed low-left with two short
cover lines stacked on the right. Signature detail: a thin cream frame inset 36px,
with the credit line inside it. Keep the scrim subtle enough for legibility.

## Style 9 — Data Story

An analytical card that treats a story like a chart. Background #F4F6F8, ink #121826,
accent electric blue (or brand accent). Typography: Space Grotesk headline 78–88px;
IBM Plex Mono for small labels and numbers. Layout: headline top; photo on a 16:9
panel with a thin border; below it a row of three "stat" labels (use only facts from
the description, never invent numbers; if no numbers exist, use three keywords).
Signature detail: small crosshair marks at the panel corners. Clean, technical.

## Style 10 — Brutalist Type

Deliberately raw, but composed. Background #E8E4DA, black type, one acid accent
used in a single strip. Typography: Archivo Black headline at 112–136px, uppercase,
line-height 0.88, text slightly oversized and clipping at the edges only if the full
headline remains readable in the safe area. Layout: photo as a black-and-white block
behind the type with a duotone tint; description in a white box with a 3px black
border. Signature detail: oversized index number "01" in the corner. No softness.

## Style 11 — Warm Documentary

Human, patient, photojournalistic. Background #EFE6D8; text #221E1A; accent burnt
orange. Typography: Source Serif 4 headline 82–96px; Work Sans for body. Layout:
photo takes the top 60% with a gentle warm overlay; a cream caption block overlaps
the bottom of the image by 40px; headline, then description, then a small source
line. Signature detail: a thin hand-drawn-style underline (SVG or border) under one
key word. Keep the photo treatment natural, no heavy filters.

## Style 12 — Paper Cut

A crafted, tactile composition made of flat paper shapes. Background pale sky;
geometric paper layers in brand pastels; one photo clipped inside a rounded arch.
Typography: Fraunces headline 80–94px; Outfit for labels. Layout: headline left,
arch photo right, description in a small paper tag at the bottom. Signature detail:
a torn-paper edge made with a CSS clip-path or repeating border. No real drop
shadows — use 2px offset solid shapes to suggest depth.

## Style 13 — Modern Luxe

A restrained fashion-house aesthetic for business and culture. Background deep
espresso (#1C1917) or cream (#F4EFE6), gold-toned accent, photo in a tall crop.
Typography: Instrument Serif headline at 90–110px, lowercase; tiny uppercase sans
for category and metadata. Layout: headline spanning the top, photo centered in a
narrow column with a metallic hairline border, description bottom in two columns.
Signature detail: a small diamond glyph between brand name and date. Expensive
through spacing, not ornament.

## Style 14 — Zine Collage

A playful cut-and-paste editorial. Background warm white with a subtle halftone
texture; black type; two pastel scraps. Typography: mixed weights — a condensed
sans headline 90–112px, a serif italic kicker, mono caption. Layout: photo tilted
1.5 degrees with a white border, headline on a torn paper strip, category on a
sticker-like rounded label. Signature detail: a small "vol. 1" stamp and a strip
of fake tape (solid translucent rectangle). Keep it legible; tilt only the photo.

## Style 15 — Blueprint

An engineered brief. Background deep navy blueprint (#0B2545) with a fine grid at
5% opacity; white technical linework; cyan accent. Typography: IBM Plex Mono for
labels, Space Grotesk bold for the headline at 76–88px. Layout: photo framed by
corner brackets, headline below, three thin callout lines with tiny labels pointing
into the image area. Signature detail: a coordinate readout and a scale bar in the
footer. No gradients; use hairlines.

## Style 16 — Tabloid Sport

High-energy but factual, for sports and entertainment. Background bold brand pastel;
black and white type; photo with a dramatic crop. Typography: Bebas Neue headline
at 120–150px, uppercase, stacked; Inter for description. Layout: headline bleeding
to the top edge inside the safe area, photo as a diagonal-cut shape, description in
a black bar with white text. Signature detail: a large outlined category word
rotated 90° in the side margin. No team logos or invented scores.

## Style 17 — Financial Daily

A trustworthy markets-desk card. Background #F7F4EE, ink #171717, accent deep green
(or brand accent). Typography: Libre Franklin headline 80–92px, semibold; IBM Plex
Mono for tickers and metadata. Layout: headline top-left, a thin rule, photo small
and rectangular on the right, description in a wide measure. Signature detail: a
tiny "MARKETS / POLICY / BUSINESS" strip above the headline and a source line in
mono. Restrained and precise.

## Style 18 — Retro Print

A 1970s print-shop palette: cream paper, rust, mustard, olive, deep brown. Use the
brand accent as one of the inks. Typography: Fraunces soft headline 88–104px;
Oswald uppercase category; rounded sans description. Layout: photo with a rounded
top and a heavy 2px ink border, headline overlapping a colored band, description in
a boxed panel. Signature detail: a small sunburst line motif and an issue number.
Visible paper grain at 4% opacity.

## Style 19 — Cosmic Dark

For science and space, without clichés. Background #080B14 with a sparse star field
(tiny dots at low opacity), off-white type, a single warm accent. Typography: Space
Grotesk headline 80–96px; Instrument Serif italic for a short quote-like kicker
(only if drawn from the source). Layout: photo as a large circle cropped by the card
edge, headline below, description in a narrow column. Signature detail: a thin orbit
arc crossing behind the headline. No nebula gradients, no lens flares.

## Style 20 — Gallery White

A contemporary museum label. Pure white background, black type, one photo, lots of
air. Typography: Instrument Serif headline 86–100px; Inter for a 22px description;
uppercase mono category. Layout: photo at the top with a 4:5 crop and 24px radius,
headline beneath, then a thin rule, then description and metadata in two columns.
Signature detail: a small framed number "No. 01" and the brand name in the bottom
corner. No color except the photo and the brand accent in a tiny mark.
