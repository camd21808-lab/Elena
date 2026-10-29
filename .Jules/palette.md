# Palette Journal

## 2025-05-18 - File Dropzones and Custom Triggers Accessibility in Elena UI
**Learning:** In Elena UI, custom dropzones with `role="button"` and `tabIndex={0}` required explicit `onDragOver`, `onDragLeave`, `onDrop` event handlers and `Space` key activation alongside `Enter`. Custom select triggers (`FieldSelect`) also required `aria-label` to provide proper screen reader context.
**Action:** Always verify `Space` key handlers and drag-and-drop support when working with custom button-like containers or file upload zones in this design system.
