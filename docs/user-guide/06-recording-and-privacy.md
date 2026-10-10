# 6. Recording and privacy

## Recording is opt-in

Audio recording is **off by default**. Two things must both be true for a session to be recorded:

1. Recording is **enabled on the server** by its administrator. If it is not, the **Record session** checkbox is greyed out and says "Disabled by server config." (This is the case on the hosted app by default.)
2. You **tick Record session before pressing Start session.** It can't be changed while a session is running.

While a recorded session runs, the header shows a red **● Recording** label.

## The consent notice

When you tick **Record session**, the app shows this notice:

> Both speakers' audio (original and translation) is saved on this server for 30 days for audit. Tell everyone on the call and get their consent before starting.

(The number of days follows the server's setting.) **Always tell everyone on the call and get their agreement first.** Some places require every participant to consent to a recording.

## What is saved

- Both sides of every turn: the speaker's original audio and the translation the listener heard, in both modes.
- Each saved file is logged in the session's record.
- Recorded sessions appear in the Review tab under **Recorded sessions**, where they can be rated.

## Retention

Recordings are **deleted automatically after 30 days** by default (the administrator can change this). The server checks for old files when it starts and every 6 hours. An administrator can also delete a session's recordings straight away.

## What is logged even without recording

For every turn, the server keeps the text (transcript and translation) and the timings, so that results can be measured. Audio is only saved when recording is on.

## Where your audio goes

- **Cascade:** audio and text pass through the Workbench server, then to each provider for its step.
- **Realtime:** your browser sends audio straight to OpenAI.

## Limits

The Workbench is an evaluation tool, not a production service. Its recording feature does not provide encryption at rest, per-participant consent records or access control on the recording files, which a production system handling medical or legal conversations would need. Don't use it for real patient or client conversations.
