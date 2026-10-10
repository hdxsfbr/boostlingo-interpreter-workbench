# Bridge

Two languages meeting in the middle: warm paper, ink-navy and a saffron accent, with an editorial serif for a human, trustworthy voice.

Fonts (Google Fonts): UI Source Sans 3, display Source Serif 4, mono Source Code Pro.

| token | hex |
|---|---|
| bg | `#FAF7F2` |
| surface | `#FFFFFF` |
| border | `#E3DCD0` |
| text | `#1B2236` |
| muted | `#5A5F6E` |
| primary | `#1F2D57` |
| onprimary | `#FFFFFF` |
| accent | `#A65F0A` |
| onaccent | `#FFFFFF` |
| primarysoft | `#ECEEF5` |
| success | `#2E7D32` |
| warn | `#8F5B00` |
| error | `#B42318` |
| bar | `#1F2D57` |
| bar2 | `#D9A35A` |

## WCAG contrast (AA normal text needs 4.5:1)

| fg / bg | ratio | AA |
|---|---|---|
| text `#1B2236` on bg `#FAF7F2` | 14.79:1 | pass |
| text `#1B2236` on surface `#FFFFFF` | 15.81:1 | pass |
| muted `#5A5F6E` on bg `#FAF7F2` | 5.96:1 | pass |
| muted `#5A5F6E` on surface `#FFFFFF` | 6.37:1 | pass |
| onprimary `#FFFFFF` on primary `#1F2D57` | 13.37:1 | pass |
| onaccent `#FFFFFF` on accent `#A65F0A` | 4.93:1 | pass |
| primary `#1F2D57` on surface `#FFFFFF` | 13.37:1 | pass |
| primary `#1F2D57` on bg `#FAF7F2` | 12.51:1 | pass |
| text `#1B2236` on primarysoft `#ECEEF5` | 13.63:1 | pass |
| accent `#A65F0A` on surface `#FFFFFF` | 4.93:1 | pass |
| success `#2E7D32` on surface `#FFFFFF` | 5.13:1 | pass |
| warn `#8F5B00` on surface `#FFFFFF` | 5.73:1 | pass |
| error `#B42318` on surface `#FFFFFF` | 6.57:1 | pass |

Files: tokens.css, logo-mark.svg, logo-wordmark.svg, mockup-interpreter.html, mockup-interpreter.png
