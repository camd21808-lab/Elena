## 2025-05-18 - File Dropzone Accessibility in Custom File Upload Components
**Learning:** Custom dropzones styled as interactive buttons (`role="button"`, `tabIndex={0}`) alongside hidden `<input type="file" />` elements lack accessible names and descriptions (`aria-label`, `aria-describedby`), leaving screen reader users without context on acceptable file types or file selection state.
**Action:** Always provide explicit `aria-label` attributes on both hidden file inputs and interactive dropzone wrappers, linking helper text via `aria-describedby` or explicit descriptions.
