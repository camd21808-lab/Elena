## 2025-03-01 - Keyboard Accessibility & ARIA Labels for Custom File Dropzones
**Learning:** Custom interactive elements with `role="button"` (like file dropzones) need both `Space` (' ') and `Enter` key handlers with `e.preventDefault()` to prevent page scrolling on Space keypress. Unlabelled form fields relying on `placeholder` text need explicit `aria-label` attributes for screen readers.
**Action:** Always include both `e.key === 'Enter' || e.key === ' '` with `e.preventDefault()` on `role="button"` elements and add `aria-label` to form controls without `<label>` elements.
