# Interpreter Workbench user guide

The Interpreter Workbench is a testing workbench built for the Boostlingo AI Interpreter assignment (Gauntlet), not a Boostlingo product. It lets you hold a spoken two-language conversation through an AI interpreter and measures how fast and how well it works. It compares two ways of building that interpreter:

- **Realtime:** one OpenAI model (`gpt-realtime`) hears the speaker and speaks the translation itself ("voice to voice").
- **Cascade:** three services in a chain. **Speech-to-text** writes down what was said, a **translation model** translates the text, and **text-to-speech** reads the translation aloud.

## Pages

1. [Getting started](01-getting-started.md): what the tool is for, logging in, headphones and the microphone.
2. [Interpreter tab](02-interpreter.md): running a conversation and reading the latency bars.
3. [Review tab](03-review.md): rating clips blind, from 1 to 5.
4. [Experiments tab](04-experiments.md): running the benchmark from the app and comparing runs.
5. [Understanding the numbers](05-understanding-the-numbers.md): latency, WER, chrF, p50/p90 and cost per minute.
6. [Recording and privacy](06-recording-and-privacy.md): what is saved, for how long, and consent.
7. [Troubleshooting and FAQ](07-troubleshooting-faq.md): common problems and fixes.

## Keyboard shortcuts at a glance

| Where | Key | What it does |
|---|---|---|
| Interpreter | Hold **F** | Talk as Speaker A (first language → second, e.g. EN → ES) |
| Interpreter | Hold **J** | Talk as Speaker B (second language → first, e.g. ES → EN) |
| Review (rating a clip) | **1**–**5** | Score the highlighted row, then move to the next row |
| Review | **Tab** / **Shift+Tab** | Move the highlight to the next / previous row |
| Review | **Space** | Play or pause the clip |
| Review | **Enter** | Save and go to the next clip |

The F/J keys work only on the Interpreter tab while a session is running. The Review keys are ignored while you type in the Notes box.
