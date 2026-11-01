# Palette's Journal - Critical UX Learnings

## 2025-05-14 - Dropzone Drag-and-Drop and Keyboard Activation Pattern
**Learning:** Visual dropzone elements in forms often advertise drag-and-drop capability in their placeholder text (e.g., "Kéo thả file vào đây..."), but without explicit HTML5 `dragover` / `dragleave` / `drop` handlers, dropping files triggers default browser navigation, causing frustrating data loss. Furthermore, custom `role="button"` dropzone elements must support both `Enter` and `Space` keys and carry explicit `aria-label` attributes to meet accessibility guidelines for keyboard and screen reader users.
**Action:** When implementing or updating custom upload dropzones, always pair visual feedback (`dragover` class) with `e.preventDefault()` on drag events, wire `dataTransfer.files`, provide both `Space` and `Enter` keyboard triggers, and ensure proper ARIA naming.
