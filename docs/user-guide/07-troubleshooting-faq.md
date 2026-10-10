# 7. Troubleshooting and FAQ

## The microphone is blocked

A red banner appears above the controls with a **Retry** button. The message tells you what went wrong:

| Message | What to do |
|---|---|
| "Microphone permission was denied." | Open your browser's site settings for this page (usually the lock or settings icon in the address bar), set **Microphone** to **Allow**, then press **Retry**. |
| "No microphone found." | Plug in a headset or microphone, then press **Retry**. |
| "No answer to the microphone prompt." | The browser's permission pop-up was not answered in time. Press **Retry** and choose **Allow**. |
| "Microphone needs a secure context." | The page was not opened over HTTPS or from `http://localhost`. Use the official address. |

Also check that no other app is holding the microphone, and that the right input device is chosen in your computer's sound settings.

## I can't hear any translation

- **Check the status label** in the header: it should read `ready`. If it doesn't, press **Start session**.
- **Hold the button the whole time you speak**, and let go when you finish. Very short or silent turns are skipped on purpose: nothing is translated if nothing was heard.
- **Check your headphones** are the computer's output device and the volume is up.
- **Look for a banner.** If a provider is unavailable or fails, a banner names the step (for example the translator or the voice). If ElevenLabs is out of credits or disabled, switch **Voice** back to OpenAI.
- **Don't speak while a translation plays.** Your mic is muted during playback, and pressing a speaker button interrupts it.

## One turn was much slower than usual

Usually this is a **temporary slowdown at one of the AI providers** (a "blip"), not a problem with the app or your connection. Open **▸ Timings** on the turn, or the latency bars: a single step (for example **TTS 1st byte**) that is much larger than usual points to that provider.

- Just try again; the next turns are usually back to normal.
- The Cascade has built-in safety nets: if a step hasn't answered after 1.5 s it sends a backup request, and it gives up on a step after 3 s (or a whole turn after 20 s) and reports a failed turn. The session continues.
- **Before measuring, do a warm-up run:** speak a turn or two in each direction and ignore their numbers. In the Experiments tab, avoid tiny runs: one 6-sentence run measured the Cascade about 0.5 s slower than normal because of a provider slow spell, while repeat runs matched the benchmark. Use at least 12 turns per setup.

## Does it work in Safari?

Yes. Safari handles the password differently from Chrome on live connections, so the app keeps you signed in with a cookie, which works in both. We don't know of any other Safari-specific limits, but the app is mostly tested in Chrome; if something misbehaves, try Chrome. In Safari, microphone permission is set under **Safari → Settings → Websites → Microphone**.

## Logout quirks

Pressing **Logout** ends your session on the server and opens a "Logged out" page with a **Log in again** link.

- **Your browser may still remember the password.** Browsers keep a typed sign-in password until they are restarted, and the app can't clear that. So after logging out, the next visit may sign you straight back in.
- **On a shared computer, close the browser completely after logging out.**

## FAQ

**Can I change the language pair mid-conversation?** No. Stop the session, change **Language pair**, and start again. You *can* switch between Cascade and Realtime mid-session.

**Why does Speaker A's button say EN → ES?** Speaker A always speaks the pair's first language and Speaker B the second. The labels change with the pair.

**Why is a translator or voice "unavailable"?** That provider is switched off on this server (for example ElevenLabs, to save free credits). The reason is shown next to it.

**Can several people rate in the Review tab?** Yes. Each person enters their own name; Results can show your ratings or all raters pooled.

**Can I run two experiments at once?** No. Only one runs at a time; wait for it to finish or cancel it.

**Where do the benchmark numbers come from?** The final benchmark run of 8 Oct 2026 ("M5"), shown as the M5 baseline in the Experiments tab.
