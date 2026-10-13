## 2025-05-18 - Custom Select and Dropzone Accessibility
**Learning:** Custom interactive elements (e.g. `role="button"` dropzones and custom `.ky-trigger` select buttons) often miss required `aria-label` attributes and Spacebar key handlers (`e.key === ' '`).
**Action:** Always ensure custom button elements support both `Enter` and `Space` keyboard events (with `e.preventDefault()`), and attach proper `aria-label` props to custom triggers and dropzone elements.
