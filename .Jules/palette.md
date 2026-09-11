## 2025-05-18 - Keyboard and Screen Reader Accessibility in Custom Controls

**Learning:** Custom `role="button"` elements (such as file upload dropzones) must handle both `Enter` and Space (`' '`) keypresses with `e.preventDefault()` to avoid unwanted page scrolling on activation. In addition, custom select dropdown trigger buttons (`aria-haspopup="listbox"`) require `aria-label` directly on the trigger element so screen readers announce the field label upon focus, not just inside the expanded listbox menu.

**Action:** Whenever creating custom interactive controls or custom dropdown triggers in React, ensure proper keyboard event handling (Enter + Space) and attach `aria-label` directly to the focusable trigger element.
