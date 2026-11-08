# Palette UX Journal

## 2026-11-08 - Dropzone Drag & Drop and Tab Semantics
**Learning:** Dropzones that prompt users to drag-and-drop ("Kéo thả file vào đây") must implement `onDragOver`, `onDragLeave`, and `onDrop` event handlers with visual cues (`.dropzone-active`). Elements with `role="button"` must support both Enter and Space keys. Tabs within `role="tablist"` require `role="tab"` and `aria-selected` attributes.
**Action:** Always check interactive file dropzones and tab bars for keyboard and ARIA compliance when auditing UX.
