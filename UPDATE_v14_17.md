# v14.17 — cold-start first-message recovery

## What the supplied log proves

The missing first message does not appear as `callback POST hit` or `received:`.
It therefore never reached the Flask callback. The second message woke/used the
now-running Render service and was processed normally.

On Render Free, a service spins down after inactivity and takes time to start.
LINE webhook redelivery is disabled by default. Without redelivery, the webhook
that triggered the cold start can be lost before Gunicorn is ready.

## Code changes

- Logs `webhookEventId`, `deliveryContext.isRedelivery`, and event age.
- Accepts redelivered webhook events through the normal reply path.
- Skips duplicate `webhookEventId` values only after an event was successfully
  handled.
- Leaves failed delivery events unmarked so a later redelivery can retry.
- Does not alter Scene Replay, persona routing, or the successful dialogue path.

## REQUIRED LINE setting (cannot be changed by Python code)

LINE Developers Console → Messaging API → **Webhook redelivery: ON**

This is the direct fix for the currently missing first webhook on a sleeping
Render service.

## Fully reliable alternative

Use an always-on Render instance. The free instance can still cold-start; LINE
redelivery substantially improves recovery but LINE does not promise absolute
delivery guarantees.
