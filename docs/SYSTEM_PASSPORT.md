# ChannelFactory — System Passport

Status: draft

This document defines **what the universal factory must be able to do**, independently of implementation technology or channel topic.

## 1. Research

- Discover and monitor relevant sources.
- Detect candidate topics/events worth covering.
- Collect source material with provenance.
- Avoid unnecessary duplication of recent material.

## 2. Editorial workflow

- Propose candidate publications.
- Select/prioritize topics according to editorial policy.
- Draft content in a configurable channel voice.
- Critique drafts for banality, factual weakness, style problems, and AI-like language.
- Fact-check where appropriate.
- Support human approval/editing before publication.
- Allow increasing autonomy later without redesigning the system.

## 3. Publishing

- Publish approved material to Telegram.
- Support text first; media can be added later.
- Keep publication history and status.

## 4. Conversational agent

- Accept natural-language user messages.
- Use an LLM as the language/reasoning core.
- Maintain conversation context.
- Access project knowledge and tools.
- Remember selected durable user preferences/state where appropriate.
- Escalate or defer cases the system should not answer autonomously.

## 5. Feedback and analytics

- Collect available engagement signals.
- Connect outcomes to individual publications/experiments.
- Feed useful evidence back into future editorial decisions.
- Keep optimization subordinate to editorial policy rather than blindly maximizing clicks.

## 6. Experiment lifecycle

Each channel experiment should have:

- hypothesis;
- target audience;
- value proposition;
- budget;
- launch date;
- evaluation checkpoints;
- success/failure criteria;
- decision: continue, modify, pause, or close.

## 7. Monetization (optional at first)

The architecture should be able to add:

- subscriptions or paid digital service;
- lead generation;
- affiliate/referral flows;
- advertising/sponsorship;
- payment status and entitlements.

## 8. Portability

The first implementation targets Telegram, but topic-specific logic should be configuration rather than hard-coded behavior wherever practical.

## 9. Cost discipline

- No permanent expensive LLM process is required.
- Invoke models only when useful.
- Use ordinary code/database operations for deterministic work.
- Allow model choice by task and cost.
- Avoid building infrastructure before the experiment proves it needs it.

## 10. Initial technical acceptance test

Before launching a real topic, the prototype should complete one end-to-end loop:

1. LLM proposes a publication from supplied/source material.
2. Human approves it.
3. System publishes it to a test Telegram channel.
4. A user asks the Telegram bot a natural-language question.
5. LLM answers using the configured context/tools.
6. Conversation/result is persisted.
7. The system records enough data to inspect what happened.

## Open questions

- Which existing platform covers the largest share of this passport?
- What requires custom code?
- What is the smallest useful persistence layer?
- How should human approval work?
- Which analytics Telegram exposes reliably for our purposes?
- How should reusable configuration be separated from experiment-specific configuration?
