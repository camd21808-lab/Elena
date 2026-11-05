# Palette's Journal - Critical UX Learnings

## 2025-11-05 - Drag-and-drop feedback and accessibility on custom file uploaders
**Learning:** Custom `.dropzone` role="button" elements that display "drag and drop" text frequently omit actual HTML5 drag events (`onDragOver`, `onDragLeave`, `onDrop`) and spacebar keyboard triggers (`e.key === ' '`), leaving keyboard and drag users without functional or visual feedback.
**Action:** When working with file upload dropzones in this design system, always implement drag event handlers with a `.drag-active` visual highlight class, bind both Enter and Space keys with `preventDefault()`, and provide an explicit `aria-label`.
