# Palette's UX Journal

## 2025-05-18 - Dropzone Drag-and-Drop and Keyboard Activation
**Learning:** Custom file dropzones styled with dashed borders often lack native drag-over/drop event handlers and keyboard Space activation, leaving users who drag files or rely on keyboard navigation without expected feedback or trigger ability.
**Action:** Always wire `onDragOver`, `onDragLeave`, and `onDrop` with an `.is-dragging` CSS state for clear visual target feedback, provide `aria-label`, and support both `Enter` and `Space` (`' '`) for keyboard file picker activation.
