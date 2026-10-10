# Relay

Boostlingo-adjacent: their verified brand blue, teal and CTA orange on clean white, with a workbench mark of our own (two hand-off arrows). It sits in their brand family without posing as their product.

Fonts (Google Fonts): UI Inter, display Inter, mono JetBrains Mono.

| token | hex |
|---|---|
| bg | `#F4F7FD` |
| surface | `#FFFFFF` |
| border | `#D9E1EE` |
| text | `#252224` |
| muted | `#585C66` |
| primary | `#1462F0` |
| onprimary | `#FFFFFF` |
| accent | `#DD3900` |
| onaccent | `#FFFFFF` |
| primarysoft | `#E8F0FE` |
| navy | `#051E4D` |
| teal | `#82C5BF` |
| success | `#1E7A3C` |
| warn | `#8A5A00` |
| error | `#B42318` |
| bar | `#1462F0` |
| bar2 | `#82C5BF` |

## WCAG contrast (AA normal text needs 4.5:1)

| fg / bg | ratio | AA |
|---|---|---|
| text `#252224` on bg `#F4F7FD` | 14.68:1 | pass |
| text `#252224` on surface `#FFFFFF` | 15.75:1 | pass |
| muted `#585C66` on bg `#F4F7FD` | 6.24:1 | pass |
| muted `#585C66` on surface `#FFFFFF` | 6.69:1 | pass |
| onprimary `#FFFFFF` on primary `#1462F0` | 5.2:1 | pass |
| onaccent `#FFFFFF` on accent `#DD3900` | 4.51:1 | pass |
| primary `#1462F0` on surface `#FFFFFF` | 5.2:1 | pass |
| primary `#1462F0` on bg `#F4F7FD` | 4.85:1 | pass |
| text `#252224` on primarysoft `#E8F0FE` | 13.75:1 | pass |
| accent `#DD3900` on surface `#FFFFFF` | 4.51:1 | pass |
| success `#1E7A3C` on surface `#FFFFFF` | 5.38:1 | pass |
| warn `#8A5A00` on surface `#FFFFFF` | 5.93:1 | pass |
| error `#B42318` on surface `#FFFFFF` | 6.57:1 | pass |

Files: tokens.css, logo-mark.svg, logo-wordmark.svg, mockup-interpreter.html, mockup-interpreter.png
