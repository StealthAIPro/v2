---
version: alpha
name: "Game Connection Stabilizer"
description: "A compact Windows connection utility with a beginner-friendly, low-glare interface."
colors:
  background: "#0A0E27"
  surface: "#0F172A"
  border: "#1E293B"
  primary: "#2563EB"
  primary-soft: "#60A5FA"
  text: "#E2E8F0"
  text-muted: "#94A3B8"
  success: "#10B981"
  warning: "#F59E0B"
  danger: "#EF4444"
typography:
  sans:
    fontFamily: "Segoe UI, sans-serif"
rounded:
  DEFAULT: "0px"
spacing:
  section-gap: "12px"
  page-padding: "16px"
components:
  titlebar: {}
  slider: {}
  scrollbar: {}
  status: {}
  card: {}
  toggle: {}
---

# Game Connection Stabilizer Design System

## Overview

Game Connection Stabilizer should feel like a compact connection-control panel for Windows users who need quick, precise control while another application is running. It is a product surface, not a marketing surface. Its signature is the uninterrupted navy application shell, including window controls. Restraint wins everywhere else: no gradients, decorative shadows, or light native controls that break the low-glare workspace.

Visible copy must use everyday terms. Prefer "Turn Stabilizer On," "Normal Traffic Delay," "Waiting," and "Running" over implementation terms such as packet interception, jitter buffer, queue depth, or standard deviation. Technical names remain acceptable inside the code and developer documentation.

The runtime Tkinter widgets in `src/ui.py` and `src/widgets.py` are the canonical implementation. This file mirrors their durable visual tokens.

## Colors

The background and surface colors establish two quiet layers. Blue identifies adjustable or active controls; green reports active state; amber and red are reserved for warning and danger. Text uses the documented primary and muted roles.

## Typography

Segoe UI is used throughout to align with the Windows environment. Labels are compact, with weight and color providing hierarchy instead of oversized type.

## Layout

The fixed-width utility layout uses 16px outer padding and compact 12px section gaps. Controls fill their cards so interaction targets remain easy to acquire. Long content scrolls inside the application body while the title bar remains stationary.

## Elevation & Depth

Hierarchy comes from tonal surfaces and one-pixel borders. Static content does not use shadows.

## Shapes

Cards and the close action use square geometry. Toggle tracks and slider thumbs are rounded only where their physical control metaphor requires it.

## Components

The title bar is dark, draggable, and visually continuous with the app. Minimize is a transparent ghost action; close gains a red surface on interaction. The slider uses a subdued track, blue progress, and a high-contrast thumb, with pointer and keyboard operation. The vertical scrollbar uses a narrow slate thumb with mouse-wheel, keyboard, track-click, and drag operation; no light native scrollbar chrome is shown. Connection and performance-mode state is reported inline: muted text for off, green for running, and red text with a recoverable explanation for failure. The interface must never display a running state after WinDivert fails to open.

## Do's and Don'ts

- **Do:** Keep every owned window and input surface within the navy palette.
- **Do:** Preserve visible focus and familiar Windows control symbols.
- **Don't:** Allow default white native controls to interrupt the application shell.
- **Don't:** use decoration where a state color or one-pixel boundary communicates the same information.
