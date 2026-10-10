# Boostlingo.com study (captured Fri Oct 9 2026, ~7:30 PM CT)

**Method.** I rendered https://boostlingo.com/ with Playwright driving the box's Chrome, at a 1280x800 viewport. A plain curl gets a Cloudflare block page, so a real browser was needed.
- Screenshots: `desktop-1280.png` and `fullpage-1280.png`. The CookieYes privacy banner overlaps the hero; it's third-party.
- Computed styles: `computed.json`.
- Raw stylesheets and SVGs: `assets/`, with their URLs in `assets/index.json`.
- Rendered DOM: `dom.html`.
- Capture script: `study.py`.

CSS source = `assets/04.css` = https://cdn-ilekkam.nitrocdn.com/CTnEqJQCAvEdtTFzLcMxFIQVDzVrzQnd/assets/static/optimized/rev-326d214/boostlingo.com/combinedCss/nitro-min-noimport-b9d75b77e8175d08c318969909bc625f-stylesheet.css

## Palette, verified
| hex | role (inferred from use) | source |
|---|---|---|
| #1462F0 | brand blue: links, nav, logo | 04.css `.elementor-kit-6{--e-global-color-abf0e17}` and `.elementor-kit-6 a{color}`; computed `a` and `nav a` color rgb(20,98,240); logo SVG fill |
| #82C5BF | brand teal: logo second colour, gradients | 04.css `--e-global-color-343d224`; logo SVG fill (assets/00.svg) |
| #DD3900 | CTA orange-red ("Request a Demo") | 04.css `--e-global-color-bbfcdda`, used by `.elementor-element-6b416c7 .elementor-button{background-color:var(--e-global-color-bbfcdda)}` |
| #252224 | body text (near-black) | 04.css `--e-global-color-f7ae645`; computed `body` color rgb(37,34,36) |
| #051E4D | deep navy | 04.css `--e-global-color-78d6a50` (I didn't locate where it's used on the page) |
| #EE7B62 | coral | 04.css `--e-global-color-eaaff6e` (I didn't locate where it's used) |
| blue→teal gradient | top utility bar | computed backgroundImage `linear-gradient(90deg, rgb(20,98,240), rgb(130,197,191))` |

Ignored: `--e-global-color-primary #6ec1e4`, `secondary #54595f` and `accent #61ce70`. These are Elementor's default kit values and don't appear in the visible design. The cookie-banner colours (#1863DC, #CC3366) belong to CookieYes, not Boostlingo.

**Unverified.** I didn't extract the exact hex of the pale-blue hero background. It's only seen in the screenshot, and the #F4F7FD used in Relay is my own choice, not theirs.

## Type
- **Verified:** the family is **"Helvetica Now"** (Monotype, paid) on body, headings, nav and buttons. Source: computed `fontFamily` on body/h1/h2/a, and 04.css `.elementor-kit-6 a{font-family:"Helvetica Now"}`.
- **Verified sizes and weights:** body 18px/300, h1 52px/500, h2 70px/500.
- **Unverified:** where the font file is served from. No @font-face for it was in the captured CSS.
- **Free substitute:** Inter. It's the closest Google Fonts neo-grotesque, and I used it at 300–600.

## Logo, imagery, tone, layout (from screenshot and SVG)
- **Logo:** lowercase "boostlingo" wordmark in blue #1462F0 and teal #82C5BF, with a separate round "b" mark (`https://cdn-ilekkam.nitrocdn.com/CTnEqJQCAvEdtTFzLcMxFIQVDzVrzQnd/assets/images/optimized/rev-badc4d6/boostlingo.com/wp-content/uploads/2024/01/boostlingo-logo.svg`). Our mark copies neither.
- **Imagery:** real human headshots in coloured rings around a globe, flat blue and teal circles, "person in a circle" icons. No dark UI.
- **Tone:** confident, plain-spoken B2B ("One Platform for Language Services", "Experience the Future of Interpreting").
- **Layout:** white header with a mega-menu, a thin gradient utility bar on top, a big light hero with copy on the left and illustration on the right, a square-cornered solid orange CTA, and an outlined blue secondary button. Radii are small (0–10px).
