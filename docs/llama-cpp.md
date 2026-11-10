# llama.cpp: a real model

The fakes answer on a timetable, which makes a backend's own cost measurable. But a benchmark of AI backends should also show them working with a real model. That's what this service is for: [llama.cpp](https://github.com/ggml-org/llama.cpp)'s server, running one small language model on the CPU, inside Compose.

A real model is slow and never answers the same way twice, so it isn't where a backend's milliseconds are measured: the [fake server](fake-server.md) is. Here a backend shows that it handles the real thing: real reasoning, real chunks, real refusals. Why it's built this way is in [0025](../spec/decisions/0025-llama-cpp-in-compose-qwen3-5-0-8b-four-slots-a-pinned-file.md). The words used here are explained in [the guide](README.md#the-words-used-here).

## Using it

It starts only when named, since its first start downloads the model:

```text
docker compose up -d --wait llama-cpp
```

It then answers on `127.0.0.1:8020`, and on Compose's network at `http://llama-cpp:8080/v1`. To have a backend call it, start the backend with two settings, in `.env` or on the command line:

```text
LLM_PROVIDER=openai-compatible LLM_BASE_URL=http://llama-cpp:8080/v1 docker compose up -d --wait go-nethttp
```

Then ask the backend, as usual:

```text
curl -N http://127.0.0.1:8002/api/chat/stream -H "Content-Type: application/json" -d "{\"messages\": [{\"role\": \"user\", \"content\": \"Say hello.\"}], \"parameters\": {\"max_tokens\": 40, \"chat_template_kwargs\": {\"enable_thinking\": false}}}"
```

- **The model reasons before it answers,** by default. With few tokens, an answer may be all `reasoning` events and no `token` event. Qwen's own parameter, `"chat_template_kwargs": {"enable_thinking": false}`, turns that off; the backend passes it on like any other.
- **`docker compose down`** stops it with the rest. `docker compose down --volumes` also deletes the downloaded model.

## How it's set up

In [`compose.yaml`](../compose.yaml), the `llama-cpp` service, in the `llm` profile:

| What | Value | Setting |
|---|---|---|
| The server | `ghcr.io/ggml-org/llama.cpp:server-b12242`, pinned by digest: the build the fake server's shapes were captured from | |
| The model | [Qwen3.5-0.8B](https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF) at Q4_K_M, 532.5 MB, Apache 2.0 | `LLAMA_MODEL_URL`, `LLAMA_MODEL_FILE` |
| Where it comes from | Its URL at the repository's commit `6ab461498e20`, downloaded once into the `llama-models` volume | |
| Slots: requests served at once | 4 | `LLAMA_SLOTS` |
| Context, shared by the slots | 8,192 tokens, so 2,048 for each | `LLAMA_CONTEXT_SIZE` |
| Images and audio | Off: the contract is text only | |
| CORS | `localhost` only, as ai-bootstrap does | |
| Limits | None: it's a helper | |
| Health | The image's own check on `/health`, which answers 503 while the model loads. The first start has 30 minutes | |
| Port | `127.0.0.1:8020` | `LLAMA_PORT` |

It isn't in CI: it needs a download, and its answers aren't fixed.

## Measured on 2026-11-10

On the development Mac: an Apple M3 with 8 cores and 8 GB, on macOS 14.3; Docker 29.5.2 in Colima's VM, with 4 CPUs and 5 GiB. The host was busy, with a load average of 3 to 6. Timing numbers from this VM are for development ([0015](../spec/decisions/0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).

**Picking the model.** Three candidates, each asked "In one sentence, what is an LLM?" for 64 tokens at most, once to warm up and once measured, through the same server:

| Model, Q4_K_M | Download | Alone | Memory | Reasons |
|---|---|---|---|---|
| SmolLM2-135M-Instruct | 105 MB | First token at 6 ms, about 300 tokens a second | 0.3 GiB | No |
| Qwen3.5-0.8B | 533 MB | First token at 126 to 562 ms, 55 to 85 tokens a second | 1.0 to 1.2 GiB | Yes, by default |
| Qwen3.5-2B | 1.28 GB | 32 tokens a second once, 1.2 once: the VM ran short of memory | 1.7 GiB | Yes, by default |

**Picking the slots.** Four requests sent at once:

| Model | Slots | First tokens at | Each ran at | All done in |
|---|---|---|---|---|
| SmolLM2-135M | 1 | 7, 37, 160 and 361 ms | 310 to 349 tokens/s | 442 ms |
| SmolLM2-135M | 4 | 51 to 131 ms | 107 to 152 tokens/s | 475 ms |
| Qwen3.5-0.8B | 1 | 0.3, 1.6, 5.0 and 6.9 s | 24 to 73 tokens/s | 7.7 s |
| Qwen3.5-0.8B | 4 | 0.7 to 2.5 s | 13 to 20 tokens/s | 5.6 s |

- **With one slot, requests wait their turn,** and each runs at full speed once it starts.
- **With four, they all start together,** and share the CPU.
- **Without a slot count, the server picked 4** on this VM.

**The service, as built:**

| What | Measured |
|---|---|
| First start, the download included | Healthy 78 s after `docker compose up -d --wait llama-cpp` |
| A later start, from the volume | Healthy in 4.9 s, with nothing downloaded |
| A start with no network at all | The model loaded from the volume, in about 6 s |
| Memory, idle once loaded | 816 MiB |
| Disk | The image, 291.8 MB; the model in its volume, 532.5 MB |

**What its stream looks like,** captured from the server: the reasoning arrives as its own chunks, as the fake server sends them.

```text
data: {"choices":[{"finish_reason":null,"index":0,"delta":{"reasoning_content":"Thinking"}}],"created":1794346312,"id":"chatcmpl-bj5l3nGbFeB4pfUsMv22JPguv74phKtk","model":"/models/Qwen3.5-0.8B-Q4_K_M.gguf","system_fingerprint":"b12242-3b4d6ab3f","object":"chat.completion.chunk"}
```

**A model's URL alone loads nothing.** Given only the model's URL, this build of the server starts in "router mode", serving no model until one is asked for. Given the URL and a path, it downloads the file to the path once, then loads it. Compose gives it both.

## Checked by the conformance suite

21 checks, 7 for each backend, in [`test_llama_cpp.py`](../bench/conformance/test_llama_cpp.py). They need the model, so they run only when asked, once llama.cpp has started:

```text
docker compose up -d --wait llama-cpp
docker compose run --rm conformance -m llama_cpp
```

| Check | What |
|---|---|
| Readiness | 200, with the `llm` check `ok` |
| The whole answer | Valid against the contract, with reasoning, its model named after the file, cut at 8 tokens with `length` |
| The stream | Valid, in order, only `reasoning` events then `done`, and never more events than tokens made |
| A parameter reaches the model | With `enable_thinking` off, only `token` events |
| A refused parameter | `"temperature": "hot"`: llama.cpp answers 400, the backend 502, whole and streamed |
| llama.cpp stopped | Readiness 503, and the whole answer 503; started again, ready again |

A real model's answers aren't fixed, so these check each answer's shape, not its text.

**On 2026-11-10,** on the Mac: 21 passed in 32.74 s. The default run of the suite skips them: it collected 648 checks and ran 627, which passed in 173.97 s.
