## 2026-10-25 - Custom Dropzone Accessibility & Drag-and-Drop Patterns
**Learning:** Custom `role="button"` file dropzones in React require explicit `onDragOver`, `onDragLeave`, and `onDrop` event handlers with `e.preventDefault()` to prevent the browser from navigating away when users drop files, as well as handling both `Space` and `Enter` keys for full keyboard accessibility.
**Action:** Always pair `role="button"` dropzone elements with drag-over state feedback (`is-dragging`), `aria-label`, native file drop handlers, and dual `Enter`/`Space` key handlers.
