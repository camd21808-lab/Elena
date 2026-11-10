# Palette's Journal - Critical UX & Accessibility Learnings

## 2025-05-10 - Card Navigation Consistency
**Learning:** In card-based views with a launcher hub, screens transitioned into from the launcher (such as tool forms and settings) require consistent, top-left "Quay lại" (Back) button navigation. While side rails / drawer navigation are available, users intuitively look for explicit back navigation on the card itself to return to the hub.
**Action:** Always include a `.card-top` with a `.ghost` back button linked to `goLauncher` on all secondary view cards to maintain unified navigation affordances across the app.
