# 20. The assistant composes the features' AI tools

Date: 2026-11-18

## Status

Accepted. Amends [ADR 11](0011-feature-sliced-backend-layout.md): a feature may keep a second
adapter, `ai_tools/`, beside `endpoints/`, and the assistant is the only feature that imports it.

## Context

The AI assistant answers from the system's data through tools the model calls: the menu first,
then bookings, tables and the cart. A tool must call the same service the HTTP route calls and
copy no rule, and the user's identity must reach it from the verified JWT, never from a model
argument. [ADR 11](0011-feature-sliced-backend-layout.md) has no place for such code: a regular
feature may import only core features, so the assistant could not reach the cart's services, and
a tool that lived inside the assistant would have to know every feature's services and data
shapes. Putting the tools into `application_services` does not fit either: that package is for
work that spans features, while a tool is an adapter of one feature for one caller, the model.

## Decision

- **`ai_tools/` is a second adapter over `services`.** A feature that offers the model something
  keeps it in `ai_tools/` beside `endpoints/`. The package imports the feature's `services`,
  `dto` and `enums`, never directly `repositories`, `models`, `schemas` or anything from FastAPI;
  in the
  layers contract it sits on the same level as `endpoints`, independent of it. A tool is a
  `StructuredTool` over a coroutine with a Pydantic argument model whose every field is
  described; it opens its own session per call, builds the service as the feature's HTTP
  dependencies do, and shapes the service's result for the model, which is not a rule.
- **The assistant is the composition root.** Only `app.features.assistant` imports `ai_tools`
  packages, core or regular, and binds them to the model per request. Every feature may own an
  `ai_tools/`; nothing else may use it, so the HTTP routes and the tools stay two independent
  faces of one service.
- **The context is bound, not passed.** `app.common.ai_tools.AiToolContext` carries the user id
  from the JWT, the sessionmaker and the settings values the tools need. No tool argument names a
  user; the model cannot choose whose data a tool reads.
- **The contracts enforce it.** `pyproject.toml` adds `ai_tools` to the layers, to the sources of
  the endpoint-level rules (no repositories or models, no schemas, no HTTP), exempts the
  assistant's imports of regular features' `ai_tools` from "Regular features are independent",
  and protects every `ai_tools` package so that only the assistant may import it.

## Alternatives considered

- **Tools inside the assistant feature.** One place to read, but the assistant would import every
  feature's services and dto, and a regular feature such as the cart would be unreachable under
  ADR 11 without a blanket exception.
- **Tools in `application_services`.** The package exists for cross-feature flows called by
  endpoints and background tasks; a tool over one feature's service is neither, and the services
  there would then depend on LangChain.
- **A tool router over tool groups.** Fewer tools bound per call, but another layer to design and
  test for a handful of tools; ruled out by the product scope.

## Consequences

- A new tool is a file in the feature it belongs to, next to the service it calls, and one line
  in the assistant's toolkit builder.
- The `ai_tools` packages depend on `langchain-core`; services, repositories and models do not.
- A feature's tools can change without touching its routes, and a route change leaves the
  tools alone, but a service change may break both, which the shared tests catch.
- A tool that needs two features' services has no home; it would be a cross-feature flow and
  belongs in `application_services` with a thin tool over it, which no story needs yet.
