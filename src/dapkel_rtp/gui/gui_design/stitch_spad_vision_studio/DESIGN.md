---
name: Deep Space
colors:
  surface: '#131315'
  surface-dim: '#131315'
  surface-bright: '#39393b'
  surface-container-lowest: '#0e0e10'
  surface-container-low: '#1b1b1d'
  surface-container: '#201f21'
  surface-container-high: '#2a2a2c'
  surface-container-highest: '#353437'
  on-surface: '#e5e1e4'
  on-surface-variant: '#b9cacb'
  inverse-surface: '#e5e1e4'
  inverse-on-surface: '#303032'
  outline: '#849495'
  outline-variant: '#3a494b'
  surface-tint: '#00dbe7'
  primary: '#e1fdff'
  on-primary: '#00363a'
  primary-container: '#00f2ff'
  on-primary-container: '#006a71'
  inverse-primary: '#00696f'
  secondary: '#ffdb9d'
  on-secondary: '#412d00'
  secondary-container: '#feb700'
  on-secondary-container: '#6b4b00'
  tertiary: '#fff5f4'
  on-tertiary: '#690003'
  tertiary-container: '#ffd0ca'
  on-tertiary-container: '#c3000a'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#74f5ff'
  primary-fixed-dim: '#00dbe7'
  on-primary-fixed: '#002022'
  on-primary-fixed-variant: '#004f54'
  secondary-fixed: '#ffdea8'
  secondary-fixed-dim: '#ffba20'
  on-secondary-fixed: '#271900'
  on-secondary-fixed-variant: '#5e4200'
  tertiary-fixed: '#ffdad5'
  tertiary-fixed-dim: '#ffb4aa'
  on-tertiary-fixed: '#410001'
  on-tertiary-fixed-variant: '#930005'
  background: '#131315'
  on-background: '#e5e1e4'
  surface-variant: '#353437'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  data-lg:
    fontFamily: JetBrains Mono
    fontSize: 18px
    fontWeight: '500'
    lineHeight: 24px
  data-md:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 18px
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.06em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 12px
  margin: 16px
  panel-padding: 8px
  sidebar-width: 280px
---

## Brand & Style
This design system is engineered for high-precision scientific instrumentation, specifically Single-Photon Avalanche Diode (SPAD) camera interfaces. The brand personality is clinical, technical, and unobtrusive, prioritizing data integrity and operator focus over decorative elements.

The aesthetic follows a **Technical Minimalism** approach:
- **High-Density Information:** Layouts are optimized to present maximum telemetry with minimum eye strain.
- **Precision Visuals:** Every line and pixel serves a functional purpose, utilizing thin 1px borders and high-contrast accents to delineate hierarchy.
- **Operational Safety:** Visual cues are designed to communicate hardware status (e.g., cooling, high-voltage) instantly through standardized color-coding.
- **Environmental Adaptability:** The interface is built for dark laboratory environments, featuring a "Red-Light Mode" to preserve the operator's scotopic vision during sensitive photon-counting experiments.

## Colors
The palette is centered on a "True Dark" foundation to minimize screen glare in optical labs.

- **Primary (Cyan):** Used for active data streams, photon counts, and primary action states. It provides high visibility against the dark background without causing significant haloing.
- **Secondary (Amber):** Reserved for telemetry warnings, hardware limits, and secondary data visualizations (e.g., timestamps).
- **Tertiary (Safety Red):** Strictly limited to high-voltage status, critical hardware errors, and emergency stop controls.
- **Neutrals:** A tiered system of dark greys creates depth without relying on shadows. Surfaces use `#1C1C1E` to distinguish modular panels from the global background.
- **Red-Light Mode:** A global state that transforms all interface highlights and text into shades of deep red (#FF3B30) and dark mahogany (#4D0000) to maintain dark adaptation for the researcher.

## Typography
The typographic system differentiates between **Control/Navigation** and **Telemetry/Data**.

- **Inter:** Chosen for labels, descriptions, and system navigation due to its exceptional legibility at small sizes and neutral character.
- **JetBrains Mono:** Utilized for all numeric readouts, time-gating parameters, and hardware addresses. The monospaced nature ensures that jumping numbers in live data streams do not cause layout shifts.

**Hierarchy Rules:**
- All data readouts (photon counts, kHz, voltage) must use the Mono scale.
- Section headers should use `label-caps` for a professional, "instrument-panel" feel.
- Mobile scaling is not required as this is a workstation-class GUI, but standard density must remain high.

## Layout & Spacing
The design system employs a **Fixed Modular Grid** designed for 4K and Ultrawide displays typical in laboratory settings.

- **Modular "Atomic" Sidebars:** Fixed at 280px. These contain collapsible panels for hardware parameters (Gate Delay, Exposure, Threshold).
- **Layout Model:** A 12-column grid with narrow 12px gutters. This high-density approach allows multiple histograms and live feeds to be docked simultaneously.
- **Spacing Rhythm:** Based on a 4px baseline. Components are packed tightly to minimize mouse travel, but separated by 1px neutral-grey borders to maintain clarity.
- **Reflow:** On smaller displays, sidebars collapse into icons, and the central data visualization expands to fill the viewport.

## Elevation & Depth
This system eschews shadows and blur effects to maintain a "Qt-native" professional aesthetic and reduce GPU overhead for live rendering.

- **Low-Contrast Outlines:** Hierarchy is established through 1px solid borders. Primary surfaces use `#2C2C2E` borders.
- **Tonal Layering:** The background is the lowest layer. Active panels sit on the Surface tier (#1C1C1E). Hover states are indicated by a subtle increase in border brightness rather than a shadow.
- **Depth through Color:** Background blurs are not used. Instead, modal overlays use a 60% opacity black tint to "recede" the background while keeping the data legible underneath.

## Shapes
Shapes are functional and sharp. A "Soft" (0.25rem) radius is applied to global containers to prevent a purely brutalist feel, but inner components (like data cells and input fields) use sharp corners (0px) to maximize screen real estate and align with the technical nature of scientific equipment.

## Components
- **Tab Bars:** Top-aligned with 2px Cyan bottom indicators for active states. Unselected tabs use a muted grey.
- **Atomic Sidebars:** Feature "Accordions" for grouping parameters. Use a chevon-down icon; headers should be `label-caps`.
- **Time-Gating Sliders:** Dual-range inputs. The track is a dark neutral, while the "active gate" window is highlighted in Primary Cyan. Thumbs are vertical bars, not circles, for precise pixel-alignment.
- **Input Fields:** Stepper-style inputs (up/down arrows) are required for all numeric parameters to allow for fine-tuning.
- **Chips/Badges:** Used for status indicators (e.g., "COOPERATIVE", "LOCKED"). These use a subtle background tint of the status color with a 1px border.
- **Data Cards:** No padding between the card border and internal histograms to allow the data to feel integrated into the hardware interface.
- **High-Voltage Warning:** A persistent, blinking (slow pulse) status indicator in the top-right corner using Safety Red when >50V is applied to the SPAD array.