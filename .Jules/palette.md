# Palette UX Learnings

## 2026-08-18 - Accessible Dropzones & Drag Hover Feedback
**Learning:** Dropzones that display copy like "Kéo thả file vào đây hoặc bấm chọn" without attaching HTML drag-and-drop events (`onDragOver`, `onDragLeave`, `onDrop`) frustrate users who naturally expect drag feedback and file drop ingestion. Furthermore, dropzones with `role="button"` need both `Enter` and `Space` key handlers (preventing page scroll on Space) and descriptive `aria-label`s.
**Action:** Always pair visual dropzone copy with real drag handlers, active drag-over visual feedback (`is-drag-over`), dual Enter/Space activation, and screen-reader accessible labeling.
