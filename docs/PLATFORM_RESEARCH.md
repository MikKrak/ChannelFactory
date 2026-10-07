# Platform Research

Status: first reconnaissance — 2026-10-07

Goal: compare existing tools against `SYSTEM_PASSPORT.md` before deciding to build custom infrastructure.

## Executive finding

There is no reason to build the ChannelFactory engine from scratch yet.

Two automation platforms currently deserve a hands-on bake-off for the first Telegram prototype:

1. **n8n** — mature general automation/orchestration platform with native Telegram support, AI agents, multiple memory backends, human approval for agent tool calls, self-hosting, and broad integrations.
2. **Activepieces** — strong new contender with native Telegram trigger/actions, a particularly convenient Telegram "Request Approval Message" action, AI agents, human approvals, tables, schedules, webhooks, API/MCP access, and self-hosting.

**Flowise** is not the first choice as the outer automation engine, but is a strong candidate for a later "AI newsroom brain": multi-agent orchestration, persistent flow state/checkpoints, human-in-the-loop, memory, retrieval, evaluation and tracing.

**Botpress** is strongest as a conversational-agent/customer-support layer. It has an official Telegram integration, but its current product direction and conversation-based pricing make it less attractive as the universal core of ChannelFactory.

**Dify** remains worth watching for AI application/workflow construction and content generation, but current evidence does not put it ahead of n8n/Activepieces for Telegram-first orchestration.

**Make** is capable and mature, but its credit/operation economics and cloud-centric model make it less attractive for our experimental factory than the two finalists.

## Passport comparison — first pass

Legend: **++** strong/native; **+** usable; **±** possible but needs glue/custom work; **?** not yet verified.

| Capability | n8n | Activepieces | Flowise | Botpress | Dify | Make |
|---|---|---|---|---|---|---|
| Telegram bot I/O | ++ | ++ | ± | ++ | ± | + |
| Telegram channel publishing | ++ | ++ | ± | ± | ± | + |
| LLM/model support | ++ | ++ | ++ | ++ | ++ | ++ |
| Agent/tool calling | ++ | ++ | ++ | ++ | ++ | ++ |
| Persistent conversational memory | ++ | ±* | ++ | + | + | ± |
| Scheduled/background flows | ++ | ++ | + | ± | + | ++ |
| Human approval | ++ | ++ | ++ | + | ? | + |
| Multi-step editorial workflow | ++ | ++ | ++ | + | ++ | ++ |
| Multi-agent newsroom | + | + | ++ | + | + | + |
| General integrations/tools | ++ | ++ | + | + | + | ++ |
| Self-hosting | ++ | ++ | ++ | —/limited fit | ++ Community | — |
| Low-cost prototype | ++ | ++ | ++ | + | ++ | + |
| Low lock-in | + | ++ | ++ | ± | ++ | ± |

\* Activepieces' own agent documentation says the agent remembers nothing between runs. Durable memory therefore needs Tables, PostgreSQL or another external persistence layer. For ChannelFactory this may be desirable because memory would belong to our engine rather than to the agent vendor.

## Candidate notes

### n8n

Strengths:
- Native Telegram node supports channel messaging and rich message operations.
- AI Agent and AI steps are integrated into workflows.
- Multiple memory options are documented, including PostgreSQL, Redis, MongoDB and others.
- Human approval can pause agent tool execution.
- Community Edition can be self-hosted.
- Mature ecosystem and large workflow/template base.

Current cloud reference price: Starter €20/month billed annually for 2,500 workflow executions; Community Edition is self-hosted.

Risk/questions:
- Need to test how pleasant the editorial approval loop feels specifically inside Telegram.
- Need to inspect workflow export/version-control ergonomics.
- Licensing should be reviewed if ChannelFactory ever becomes a distributed commercial product rather than our own service.

### Activepieces

Strengths:
- Native Telegram "New Update" trigger and 20 actions.
- Telegram can send text/media/polls and, importantly, **Request Approval Message** and wait for approval/disapproval.
- AI agents and human approvals are first-class features.
- Tables, schedules and webhooks are built in.
- 760+ integrations; unsupported APIs can be called over HTTP.
- Open-source integrations and self-hosting.
- MCP (Model Context Protocol) exposure is built in, potentially useful for letting external AI agents operate ChannelFactory.
- Cloud Free tier: 100 credits/day; Plus is $16/month annually ($20 monthly), 10,000 credits/month and own AI-provider keys.

Weakness:
- Built-in agent currently has no memory between runs. We must explicitly provide durable memory via Tables/PostgreSQL/etc.

This is currently the most interesting surprise candidate for the **fastest first Telegram prototype**.

### Flowise

Strengths:
- Purpose-built for generative-AI applications rather than generic automation.
- Agentflow supports single-agent and multi-agent systems.
- Strong human-in-the-loop: workflow checkpoints survive restarts and can resume after approval/input.
- Memory, retrieval-augmented generation, evaluation, tracing, API and self-hosting are core capabilities.
- Particularly well suited to a future editorial hierarchy: editor/supervisor → researcher → author → critic/checker.

Weakness:
- Less attractive as the outer Telegram/integration/scheduling shell than n8n or Activepieces.

Possible later architecture:
`Telegram → n8n/Activepieces → Flowise editorial brain → persistence/tools → Telegram`.

Do **not** introduce this extra layer until a simple prototype proves it necessary.

### Botpress

Strengths:
- Official Telegram integration.
- Strong conversational agent tooling, knowledge retrieval and human handoff.
- Excellent fit for support-style bots.

Weaknesses for ChannelFactory:
- Telegram integration is focused on conversations rather than running a whole publishing/research factory.
- Current product direction is strongly customer-support/helpdesk oriented.
- New pricing is conversation-based; paid plans become expensive compared with our experimental needs.

Conclusion: keep as a possible specialist conversational layer, not current core.

### Dify

Strengths:
- Strong AI workflow/app builder.
- Official quick-start demonstrates multi-platform content generation with voice/tone, branching and iteration.
- Community self-hosted edition exists.

Question:
- Telegram-first orchestration and our exact approval/publishing loop need more validation before promoting it to the finalists.

### Make

Strengths:
- Mature automation platform.
- AI agents and custom AI providers supported.

Weakness:
- Credit accounting applies to operations/tools and AI usage.
- Cloud/service economics and portability are less aligned with our desire for a reusable experimental engine.

## Recommended experiment

Do **not** choose a winner from documentation.

Build the same tiny acceptance loop twice:

### Bake-off A — Activepieces
1. Manual/scheduled trigger.
2. LLM drafts one test post.
3. Telegram sends the draft to Михаил with Approve/Reject.
4. On approval, publish to a private test Telegram channel.
5. Telegram bot receives a natural-language question.
6. LLM answers.
7. Store the interaction in a simple durable table/database.

### Bake-off B — n8n
Repeat exactly the same acceptance loop.

Measure:
- elapsed setup time;
- number of custom-code steps;
- quality of Telegram approval UX;
- ease of debugging;
- ease of exporting/versioning workflows in GitHub;
- ease of separating universal engine from channel configuration;
- actual execution/LLM cost.

## Current recommendation

**First hands-on candidate: Activepieces. Second: n8n.**

This is deliberately provisional. If Activepieces' missing built-in cross-run agent memory or workflow/versioning becomes awkward, n8n may win immediately. If both become clumsy once the editorial logic becomes genuinely agentic, add Flowise as the AI brain rather than replacing the outer automation layer.

## Sources checked

Official documentation/pricing from n8n, Activepieces, Flowise, Botpress, Dify and Make, checked 2026-10-07.

## Next action

Create a private Telegram test channel + bot and run the Activepieces acceptance loop before adding custom code.
