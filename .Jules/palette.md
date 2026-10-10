## 2026-10-10 - Custom Interactive Controls Accessibility
**Learning:** Custom `role="button"` elements (such as custom file dropzones) and dropdown triggers often missing Spacebar key activation (`e.key === ' '`) and `aria-label` screen reader attributes.
**Action:** Always complement `onKeyDown` handlers with both `Enter` and `Space` activation (`e.preventDefault()` on Space to prevent page scroll) and provide explicit `aria-label` attributes for non-native button controls.
