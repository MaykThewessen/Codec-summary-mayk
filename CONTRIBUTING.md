# Adding a domain page

Every page in this repo answers the same question for a different kind of data: *which codec or format wins, and exactly where*. They share a method, a build pipeline and a visual system. Follow this and a new page will look and behave like the existing ones.

The images page (`docs/image_codec_tradeoff_map.html`, template at `scripts/page_template.html`) is the reference implementation. Read it before starting.

## Method rules

These are not stylistic. They are what makes the pages worth reading.

1. **Measure, do not assert.** Every number on a page comes from a script in `scripts/`. If something cannot be measured in this environment, say so explicitly on the page and mark any cited figure as cited, with its source.
2. **Compare at matched perceptual quality, never at matched settings.** Quality sliders are not comparable across encoders. Sweep each codec on its own ladder, score with a perceptual metric, then interpolate each codec's own curve to a fixed quality target before comparing. `scripts/analyse.py` shows the pattern.
3. **Do not let a ladder decide the result.** If one codec's sweep stops earlier than another's, the comparison at that end is an artefact of your sweep, not a finding. Extend the ladders until every codec spans the whole range. This changed a headline number on the images page.
4. **Generate the prose that contains numbers.** `scripts/make_prose.py` derives every numeric sentence from the measurement files, so re-running a sweep cannot leave the text contradicting the charts. Do the same.
5. **State the pessimistic cases.** Where a weaker encoder was used than a practitioner would use, say so and say which direction it biases the result.
6. **Report what you could not do.** A missing measurement stated plainly is worth more than a plausible guess.

## Layout

```
scripts/<domain>/     measurement, analysis, prose, and the page template
data/<domain>/        raw sweep output and derived analysis, as JSON
docs/<domain>_*.html  the built page
testdata/             corpora, fetched by a script rather than committed
```

Build with the shared script, passing one assembled JSON payload:

```bash
python3 scripts/build_page.py scripts/<domain>/page_template.html \
        docs/<domain>_map.html data/<domain>/page_data.json
```

It inlines the fonts from `assets/fonts/` and substitutes `@@DATA@@`, so the published page fetches nothing at runtime.

## Visual system

Start from `scripts/page_template.html`. Keep its `<style>` block and its JavaScript utilities (`el`, `showTip`, `niceTicks`, `fmtInt`, the slot constants) essentially as they are, and replace the content sections and chart renderers. Consistency across pages matters more than novelty on any one of them.

### Tokens

Light values on bare `:root`; dark values repeated under **both** `@media (prefers-color-scheme: dark) { :root:where(:not([data-theme="light"])) }` and `:root[data-theme="dark"]`. Never declare a colour only inside a media or `[data-theme]` block: the default "system" state stamps no attribute, and such a colour never applies there. `body` must set an explicit background from a token.

### Colour

| Role | Light | Dark |
|---|---|---|
| Series slot 1 | `#2a78d6` | `#3987e5` |
| Series slot 2 | `#eb6834` | `#d95926` |
| Series slot 3 | `#1baf7a` | `#199e70` |
| Series slot 4 | `#eda100` | `#c98500` |
| Series slot 5 | `#e87ba4` | `#d55181` |
| Status good / warn / serious | `#0ca30c` / `#fab219` / `#ec835a` | same |

Use the slots **in order**, never cycled, never generated. This exact five-slot run is validated for colourblind separation in both modes. Status colours are reserved for state and always ship with a text label, never colour alone.

Ordered tiers (reach, support level, anything with a natural order) use **one hue at increasing wash depth**, not different hues. The region map does this: `--wash-1/2/3`.

### Marks

Bars capped at 24px with a 4px rounded data-end; lines 2px; markers at least 8px with a 2px surface ring; gridlines solid hairlines, never dashed; area fills around 10% opacity. Text always wears ink tokens, never the series colour. A legend is present for two or more series; direct-label selectively, never every point. When end-labels collide, use leader lines rather than stacking them.

### Non-negotiables

- **Never a dual-axis chart.** Two measures of different scale become two panels, as on the JPEG knee chart.
- Every chart has a **table-view twin** in a `<details>` element.
- Every chart has **hover tooltips** with hit targets larger than the marks.
- Grid children need `min-width: 0`, or nowrap content inflates the track and clips.

## House style

- No em-dashes anywhere, in prose or code comments. Use colons, commas or parentheses.
- Numbers up to four digits plain (`8760`); from five digits use a dot thousands separator (`18.222`).
- `snake_case` filenames throughout.
- Tight and factual. Prefer small tables to paragraphs.

## Verifying

Rendering it and looking at it is part of the job, not optional. The validator checks colour, not layout.

```python
from playwright.sync_api import sync_playwright
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
# launch with executable_path=CHROME; do not run `playwright install`
```

Check at 1280px light, 1280px dark and 420px narrow. Each must have zero console errors and no horizontal document overflow. Then screenshot, slice, and actually look for clipped labels, collisions and empty grid cells.
