# ChannelFactory

Universal AI-powered platform for rapidly creating and testing autonomous content channels.

## Purpose

ChannelFactory is an experimental platform for building, launching, and evaluating AI-assisted content channels from reusable components rather than rebuilding each project from scratch.

The first target platform is Telegram, but the architecture should remain as channel-agnostic as practical.

## Current phase

**Phase 0 — technical reconnaissance and system passport.**

Before choosing the first business topic, we will:

1. Define the capabilities required from the universal factory.
2. Research existing platforms and components (n8n, Flowise, Botpress, and alternatives).
3. Decide what to reuse, configure, or build ourselves.
4. Assemble a minimal end-to-end technical stand.
5. Only then choose and launch the first real channel experiment.

## Working principle

A new channel should eventually be mostly configuration:

- topic and audience;
- sources;
- editorial policy and voice;
- tools and knowledge;
- conversational agent behavior;
- product and monetization;
- experiment budget and success criteria.

The reusable engine should handle research, editorial workflow, publishing, user interaction, memory, analytics, and experiment lifecycle.

## Repository map

- `docs/` — system passport, architecture, research, and decisions.
- `workflows/` — exported automation/agent workflows.
- `src/` — custom code only where needed.
- `config/` — reusable configuration templates.
- `experiments/` — per-channel experiment configurations and notes.

## Next step

Complete `docs/SYSTEM_PASSPORT.md`, then compare candidate platforms against it.
