# Glossary

Working vocabulary for the Halogen/Kyojin comparison. English terms are canonical:
the published artifact is written in English, so every term below is the term that
appears in it.

## Engine

The inference server runtime that loads a pack and answers requests. Halogen and
Kyojin are engines. An engine is not a model and not a pack.

## Pack

The quantized weight bundle an engine loads. Distinguished from the model it was
quantized from: Halogen loads an `.hgn` checkpoint, Kyojin loads an EXL3 pack, and
both were quantized from Qwen3.8-Flash-Next.

## Reference configuration

Halogen's daily settings, taken as given and not varied: full context, vision on,
the local chat template, speculative decoding, prompt cache. The comparison measures
how another engine behaves when raised to this configuration. It is the yardstick,
not a variable — so there is exactly one arm, not a "fair" arm and a "real" arm.

## Session (as opposed to slot)

A request decoded alongside other requests inside one engine. Kyojin exposes the
count as `--sessions` and defaults to one; Halogen exposes it as `KV_SLOTS` and runs
four. Not to be confused with a conversation.

## Slot

Halogen's name for one of the four parallel request positions over its shared
262144-position pool. Used only when talking about Halogen; "session" is the
engine-neutral term.

## Digest

An immutable image identity. A tag can be moved to a new image, so every run records
the digest, never just the tag.

## Swap

Stopping one engine and starting the other. The only way to alternate between them,
because both cannot be resident on the host at the same time. A swap is an
operation with a cost (startup time, host memory state), and that cost is itself
part of what gets reported.

## Cold start

First start of an engine whose compile/tuning cache is empty. Pays kernel
compilation and table tuning.

## Warm start

Start of an engine whose compile/tuning cache survives from a previous run. This does
not specify OS page-cache state and is not synonymous with a host reboot.

## Provenance

What a measurement has to carry to be usable: which engine, which phase, which image
digest. A number without provenance is a number nobody can check, so the client refuses to
write one and the reader refuses to accept a phase that cannot produce it.

## Prefix reuse

The second request that sends the same long prefix as the first. An agent turn re-sends
its whole history, so this, not cold prefill, is what a daily user feels.

## Published tree

The allowlisted copy of the working repository that goes public. Generated, not assembled
by hand, and never a mirror of history.

## Container experience

The packaging-quality axis: whether the published container image starts, documents
itself accurately, stops cleanly, keeps what it must keep across restarts, and tells
you what went wrong. Reported separately from engine performance, because a fast
engine that is painful to run is a different problem from a slow one.
