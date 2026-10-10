# Signal

An engineer's oscilloscope: a dark, high-density console where latency and live state glow like instrument readouts.

Fonts (Google Fonts): UI Inter, display Inter, mono JetBrains Mono.

| token | hex |
|---|---|
| bg | `#0E1116` |
| surface | `#161B22` |
| border | `#2A313C` |
| text | `#E6EAF0` |
| muted | `#9AA4B2` |
| primary | `#5B9BFF` |
| onprimary | `#0B1220` |
| accent | `#F5B83D` |
| onaccent | `#0B1220` |
| primarysoft | `#1B2A44` |
| success | `#3FC27A` |
| warn | `#F5B83D` |
| error | `#FF6B6B` |
| bar | `#5B9BFF` |
| bar2 | `#2F5A9E` |

## WCAG contrast (AA normal text needs 4.5:1)

| fg / bg | ratio | AA |
|---|---|---|
| text `#E6EAF0` on bg `#0E1116` | 15.66:1 | pass |
| text `#E6EAF0` on surface `#161B22` | 14.33:1 | pass |
| muted `#9AA4B2` on bg `#0E1116` | 7.5:1 | pass |
| muted `#9AA4B2` on surface `#161B22` | 6.86:1 | pass |
| onprimary `#0B1220` on primary `#5B9BFF` | 6.76:1 | pass |
| onaccent `#0B1220` on accent `#F5B83D` | 10.53:1 | pass |
| primary `#5B9BFF` on surface `#161B22` | 6.24:1 | pass |
| primary `#5B9BFF` on bg `#0E1116` | 6.82:1 | pass |
| text `#E6EAF0` on primarysoft `#1B2A44` | 11.9:1 | pass |
| accent `#F5B83D` on surface `#161B22` | 9.73:1 | pass |
| success `#3FC27A` on surface `#161B22` | 7.59:1 | pass |
| warn `#F5B83D` on surface `#161B22` | 9.73:1 | pass |
| error `#FF6B6B` on surface `#161B22` | 6.23:1 | pass |

Files: tokens.css, logo-mark.svg, logo-wordmark.svg, mockup-interpreter.html, mockup-interpreter.png
