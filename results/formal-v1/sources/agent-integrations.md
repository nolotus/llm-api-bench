> ## Documentation Index
> Fetch the complete documentation index at: https://docs.lithosai.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Agent Integrations

> Connect popular coding agents to LithosAI.

LithosAI exposes the OpenAI Chat Completions API. Agents that support this protocol
connect directly; Codex and Claude Code use a local compatibility adapter.
Choose your agent below for setup instructions.

| Agent | Client protocol | Integration path |
| - | - | - |
| [Cline](/agent-integrations/cline) | Chat Completions | Direct |
| [DeepSeek Harness](/agent-integrations/deepseek-harness) | Chat Completions | Direct |
| [Hermes Agent](/agent-integrations/hermes-agent) | Chat Completions | Direct |
| [Codex](/agent-integrations/codex) | Responses API | LiteLLM compatibility adapter |
| [Kilo Code](/agent-integrations/kilo-code) | Chat Completions | Direct |
| [Claude Code](/agent-integrations/claude-code) | Anthropic Messages API | LiteLLM compatibility adapter |
| [omp](/agent-integrations/omp) | Chat Completions | Direct |
| [OpenClaw](/agent-integrations/openclaw) | Chat Completions | Direct |
| [OpenCode](/agent-integrations/opencode) | Chat Completions | Direct |
| [OpenHands](/agent-integrations/openhands) | Chat Completions | Direct |
| [Pi](/agent-integrations/pi) | Chat Completions | Direct |
| [VS Code (built-in chat)](/agent-integrations/vscode) | Chat Completions | Direct |

## Choose a model and reasoning effort

Choose the exact model ID from [Models](https://console.lithosai.cloud/models).
Speed tiers have distinct IDs, such as `moonshotai/Kimi-K3-fast` or
`moonshotai/Kimi-K3-ultra`. To use another model, choose its full ID, such as
`deepseek-ai/DeepSeek-V4.1-Flash-fast`. Reasoning effort is a separate setting.

| Agent | Choose a model | Change effort |
| - | - | - |
| OpenCode | `/models` | `/variants` |
| Pi | `/model` | `/settings` |
| Hermes | `/model` | `/reasoning` |
| Kilo CLI | `/models` | `/variants` |
| Cline CLI | `/model` | Start or resume with `--thinking low` or `--thinking high` |
| omp | `/switch` | Shift+Tab |
| OpenClaw local TUI | `/models` | `/think` |
| DeepSeek Harness Web UI and desktop app | Model menu, then **Model** | Model menu, then **Effort** |
| VS Code | Model picker in the Chat view | **Thinking Effort** in the model picker |

Each guide includes the provider configuration and model and effort controls.

## Before you begin

Install the agent you want to use, create a key on the [API Keys](https://console.lithosai.cloud/keys)
page, and confirm the model ID on the [Models](https://console.lithosai.cloud/models) page.
Follow your agent’s guide to save the key in its settings, secret file, or runtime
environment. You can keep using your existing editor, CLI, or Gateway.

<Note>
  LithosAI validates tool schemas strictly. An agent that loads an MCP server whose tool
  parameters are not a JSON Schema object is rejected with `invalid 'parameters' schema`.
  Disable that server or correct its schema.
</Note>

## Common issues

These apply to every agent guide.

### Limitations

* The minimal configuration enables text and tool calls. Turn on image input, reasoning, or
  other capability flags only when the selected LithosAI model supports them.
* Set the context window and maximum output from the selected model’s
  [Models](https://console.lithosai.cloud/models) page. The configuration examples use the
  limits from that page. A lower context window makes the agent compact earlier and reduces
  the cost of each request.
* Reasoning tokens and the final answer share the output budget. Selecting `max` effort
  does not increase that budget. If a response ends with `finish_reason: length`,
  increase the output budget within the model’s limit and allow room for the input.
* Keep your LithosAI API key in the agent's own settings or an environment variable. Do not
  commit it to a project repository.

### Troubleshooting

| Symptom | Cause |
| - | - |
| Authentication fails with `invalid API key` | The LithosAI API key is wrong, expired, or not visible to the process that runs the agent. If the environment variable is unset, some agents send no key at all. |
| ``the model `<id>` does not exist``, or the model is not selectable | The model ID does not exactly match the value on the [Models](https://console.lithosai.cloud/models) page. IDs are case-sensitive. |
| Context usage or compaction is inaccurate | Update the context window and output limit from the Models page. |
| Requests return `404` | The base URL must be `https://api.lithosai.cloud/v1`, unless the agent page says otherwise. |
| Requests return `400` with `invalid 'parameters' schema` | An MCP server provides a tool whose parameters are not valid JSON Schema. Disable that server or fix its schema. |
| Requests return `400` with `unknown_parameter` | The agent sends a request field LithosAI does not accept. Remove the option that adds it; the agent page names known cases. |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.