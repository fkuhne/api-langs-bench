# The fake upstream server

The upstream that isolates a backend's own cost, its HTTP client included: a server shaped like llama.cpp's, which streams the contract's tokens at the contract's pace ([0004](../spec/decisions/0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md)). How it's built, and why, is in [0023](../spec/decisions/0023-the-fake-upstream-server-go-in-its-own-module-shaped-as-llama-cpps-chunks.md). It's plan step 2.1.

## What llama.cpp sends

What the fake server imitates, captured on 2026-11-10 on the development Mac (Apple M3, Docker 29.5.2 in Colima's VM):
- **The server:** the image `ghcr.io/ggml-org/llama.cpp:server` at digest `sha256:4d2de15a0ffbce704777c64026b40512a71e0bbc0b303a5fe5ea9bf71760dff9`, 291.8 MB, which reports the build `b12242-3b4d6ab3f` and four slots.
- **The model:** [`stories260K.gguf`](https://huggingface.co/ggml-org/models/blob/main/tinyllamas/stories260K.gguf), 1,185,376 bytes. It writes nonsense, quickly, which is enough to see the chunks.
- **The command:** `llama-server -m /models/stories260K.gguf --host 0.0.0.0 --port 8080 -c 512`, then `curl` from a container on the same Docker network.

**A stream,** asked with `"stream": true`, `"stream_options": {"include_usage": true}` and `"max_tokens": 4`. Its headers:

```text
HTTP/1.1 200 OK
Server: llama.cpp
Access-Control-Allow-Origin:
X-Accel-Buffering: no
Content-Type: text/event-stream
Keep-Alive: timeout=5, max=100
Transfer-Encoding: chunked
```

Its eight events, of which the second to the fifth are a token each. The four tokens shown once:

```text
data: {"choices":[{"finish_reason":null,"index":0,"delta":{"role":"assistant","content":null}}],"created":1794319621,"id":"chatcmpl-07HESjGdwl4wxzcWyJxFQJiyrSx1ihdO","model":"/models/stories260K.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion.chunk"}

data: {"choices":[{"finish_reason":null,"index":0,"delta":{"content":"H"}}],"created":1794319621,"id":"chatcmpl-07HESjGdwl4wxzcWyJxFQJiyrSx1ihdO","model":"/models/stories260K.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion.chunk"}

data: {"choices":[{"finish_reason":"length","index":0,"delta":{}}],"created":1794319621,"id":"chatcmpl-07HESjGdwl4wxzcWyJxFQJiyrSx1ihdO","model":"/models/stories260K.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion.chunk"}

data: {"choices":[],"created":1794319621,"id":"chatcmpl-07HESjGdwl4wxzcWyJxFQJiyrSx1ihdO","model":"/models/stories260K.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion.chunk","usage":{"completion_tokens":4,"prompt_tokens":46,"total_tokens":50,"prompt_tokens_details":{"cached_tokens":0}},"timings":{"cache_n":0,"prompt_n":46,"prompt_ms":27.839,"prompt_per_token_ms":0.605195652173913,"prompt_per_second":1652.3582025216424,"predicted_n":4,"predicted_ms":11.083,"predicted_per_token_ms":3.6943333333333332,"predicted_per_second":270.68483262654513}}

data: [DONE]
```

- **A token's event is 254 or 255 bytes,** of which the token is one. The role's is 274, the finish reason's 245, and the usage's 571.
- **Every event is one `data:` line and a blank line,** with line feeds alone.

**A whole answer,** with `"max_tokens": 4`, as `application/json; charset=utf-8`, 630 bytes:

```json
{"choices":[{"finish_reason":"length","index":0,"message":{"role":"assistant","content":"\"Gra"}}],"created":1794319622,"model":"/models/stories260K.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion","usage":{"completion_tokens":4,"prompt_tokens":46,"total_tokens":50,"prompt_tokens_details":{"cached_tokens":45}},"id":"chatcmpl-EwDZRIwwMXOg1OQBNb0HQZpNoScdmy5c","timings":{"cache_n":45,"prompt_n":1,"prompt_ms":0.383,"prompt_per_token_ms":0.383,"prompt_per_second":2610.9660574412533,"predicted_n":4,"predicted_ms":0.59,"predicted_per_token_ms":0.19666666666666666,"predicted_per_second":5084.745762711865}}
```

**Its errors:**

| Request | Answer |
|---|---|
| `"messages": "no"` | 400, `{"error":{"code":400,"message":"Expected 'messages' to be an array","type":"invalid_request_error"}}`, with `Connection: close` |
| `"temperature": "hot"`, with `"stream": true` | 400, the same shape, as plain JSON: no stream starts |
| `"fake_error": {"status": 503}`, a parameter it doesn't know | Ignored: the stream above was asked with it |

**From its code,** [`server-context.cpp`](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-context.cpp), read on 2026-11-10:
- **It waits for the first result before it answers.** An error before the first token is a plain HTTP error, "to match the OAI API behavior", and a stream's headers leave with its first token.
- **An error after that** is sent as `data: {"error": …}`, and the stream ends there.
- **A client that leaves** stops the generation: each wait checks whether the connection is closed.
- **A comment line, `:`,** may be sent as a ping, on a setting.

**From its README:** the reasoning comes in `reasoning_content`, "similar to Deepseek API". A reasoning chunk wasn't captured: this model doesn't reason. Plan step 2.3 captures one.
