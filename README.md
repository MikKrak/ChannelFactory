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

## Collaborative editing

Shared document editing uses the project **Notebook (Блокнот)** protocol: a Notebook is a native ChatGPT Writing Block with **Open in editor**, while the repository file remains the canonical persistent copy. Opening does not save; synchronization back to GitHub is explicit and conflict-checked.

See `docs/NOTEBOOK_PROTOCOL.md` for the mandatory workflow.


## Architecture principles

### 1. The automation engine is replaceable

ChannelFactory must not depend conceptually on Activepieces, n8n, or any other automation engine.

The engine is an **execution layer**, not the owner of ChannelFactory's business logic.

Channel-specific and product-specific meaning should live in ChannelFactory-controlled configuration and data wherever practical, including:

- audience and value proposition;
- editorial policy and voice;
- source policy;
- agent roles and instructions;
- memory model;
- experiment hypothesis, budget and success criteria;
- monetization rules.

The automation engine may execute actions such as:

- schedule a run;
- call a language model;
- read/write persistence;
- request human approval;
- call an external service;
- publish to Telegram;
- collect results.

The initial implementation may use Activepieces or another existing engine to learn what the system actually needs. Over time, individual responsibilities may move into a custom **ChannelFactory Engine**.

The target migration path is:

```text
ChannelFactory + existing automation engine
        ↓
existing engine + ChannelFactory custom modules
        ↓
hybrid: selected flows moved to ChannelFactory Engine
        ↓
ChannelFactory Engine (if and when justified)
```

A successful migration should not require redesigning channel configurations or experiment definitions.

**Design test:** if replacing Activepieces would force us to rewrite the meaning of a channel, too much ChannelFactory logic has leaked into the automation engine.

## Next step

Complete `docs/SYSTEM_PASSPORT.md`, then compare candidate platforms against it.
