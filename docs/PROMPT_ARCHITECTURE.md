# Prompt Architecture

Yumi builds each model turn as layered context, then provider adapters map the
internal OpenAI-style message list to OpenAI-compatible, Claude, Gemini, or
other provider wire formats.

## Layers

1. **Base identity**
   - Yumi's persona, tone, language behavior, honesty rules, and context rules.
   - Stored in `DEFAULT_SYSTEM_PROMPT`, plus plugin sections and user addenda.

2. **Stable User Context**
   - Durable long-term memories such as profile, preferences, routines, projects,
     relationships, constraints, communication style, and `do_not_assume`.
   - Injected as its own system message every turn when saved memories exist.
   - Managed through built-in tools: `remember_user_context`,
     `list_user_context`, and `forget_user_context`.

3. **Turn Runtime Context**
   - Fresh, turn-only context collected before generation.
   - Includes connected edge summaries and autorun context results grouped by
     local tools and by edge.
   - Produced by `mode="autorun"` tools (legacy wire flag:
     `proactive_context`) and never persisted to chat history.

4. **Conversation history**
   - Recent user/assistant/tool transcript plus query-relevant structured memory.
   - The recent transcript is the current session plus sibling sessions for the
     same owner (`voice_`, `tg_`, `dc_`, `line_`, `chat_`), with sibling turns
     labeled by channel. It is not an unbounded dump of every conversation.

5. **Current user input**
   - The user's message for this turn. Runtime context is never mixed into the
     user's message body.
   - Added as the final user message, separate from the stored recent transcript.

6. **Callable tools**
   - Passed through the provider's tool/function API. Pinned tools are exposed
     every turn outside the dynamic retrieval cap; dynamic tools are selected by
     routing; autorun tools are not exposed as callable tools for that turn.

7. **Tool results**
   - Added only after the model requests a tool call and the runtime executes it.

## Provider Mapping

- OpenAI-compatible providers receive system messages, user/assistant history,
  and `role="tool"` results.
- Claude receives combined system text as a top-level system parameter; tool
  calls/results are converted to `tool_use` / `tool_result` content blocks.
- Gemini receives combined system text as `system_instruction`; assistant turns
  map to `model`, and tool results map to function response parts.

Keep new prompt behavior in Yumi's internal layers first. Provider adapters
should only translate that structure to a provider-specific payload.
