# Palette's Journal - Critical UX & Accessibility Learnings

## 2025-05-18 - Native Drag-and-Drop and Keyboard Parity on Custom Dropzones
**Learning:** Custom file dropzone components (`role="button"`) often mention drag-and-drop in placeholder copy ("Kéo thả file vào đây...") but default to only firing hidden file inputs on click. Without native `onDragOver` (with `e.preventDefault()`) and `onDrop`, dropping a file triggers browser default file navigation. Furthermore, standard button accessibility requires supporting both `Enter` and `Space` (` ` / `Spacebar`) with `preventDefault()` to prevent unwanted scrolling and allow keyboard-only users seamless interaction.
**Action:** When implementing or polishing dropzone UI, always pair click handlers with native drag-and-drop events, `dragging` CSS feedback, `aria-label` announcing the selected file state, and `Enter`/`Space` keyboard triggers.
