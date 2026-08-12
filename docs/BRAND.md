<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# VerseLatch visual identity

## Mark

The VerseLatch mark represents lyric lines meeting a timing rail. The full-color and symbolic SVG files in `data/` are first-party project artwork created for VerseLatch; no external logo, icon pack, font file, or downloaded SVG is incorporated into them.

The application mark deliberately avoids generic microphone, AI-sparkle, padlock, music-note, and download metaphors.

## Typography

VerseLatch bundles no custom interface font. Normal interface text follows GTK/libadwaita and the user's system typography. Monospace styling is limited to data where fixed-width alignment materially improves readability, such as LRC timestamps and technical readouts.

## UI icons

Ordinary controls use symbolic icon names provided by the GTK/GNOME icon theme. They are referenced by name at runtime rather than copied into the project.

## Source assets

- `data/io.github.erhansavas.verselatch.svg`
- `data/io.github.erhansavas.verselatch-symbolic.svg`

Current first-party artwork is attributed to erhansavas and licensed according to its SPDX headers. Any future third-party or contributor-owned visual asset must preserve its own provenance and license metadata.

## Product language

VerseLatch uses functional, neutral interface text. The workbench does not use a
marketing slogan, AI terminology, trust badges, fake metrics, repeated privacy
claims, or decorative status chips. Explanations belong next to the decision
that needs them; legal, privacy, and provenance details use progressive
disclosure through the primary menu and project documentation.

## Interface discipline

- Prefer standard GTK/libadwaita widgets and style classes over bespoke chrome.
- Use one visually suggested action for the current step; other actions stay
  neutral unless they are genuinely destructive.
- Do not override libadwaita's semantic accent/focus colors.
- Keep typography to system styles such as `body`, `heading`, `caption`, and the
  restrained title hierarchy.
- Use cards only when they express a real content group; do not turn every value
  into a dashboard tile.
- Keep appearance controls in the primary menu rather than occupying permanent
  header-bar space.
- Keep the main workbench free of repeated “local”, “telemetry”, license, or
  security slogans. About/Legal is the UI source of truth for those details.

