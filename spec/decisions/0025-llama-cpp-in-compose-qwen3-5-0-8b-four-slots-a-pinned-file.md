# 0025. llama.cpp in Compose: Qwen3.5-0.8B, four slots, and a model file pinned by its commit

- Status: Accepted
- Date: 2026-11-10

## Context

Plan step 2.3 puts llama.cpp's server in Compose, with one small model on CPU, so a backend can be pointed at a real model (R2). It's the third local upstream, beside the in-process fake and the fake server ([0004](0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md)). A real model's answers take seconds and differ from run to run, so it's there to see the backends work for real, not to time their own cost.

What was run on 2026-11-10, on the development Mac (Docker's VM with 4 CPUs and 5 GiB, the host busy), with the server image `ghcr.io/ggml-org/llama.cpp:server-b12242`, the build the fake server's shapes were captured from ([fake server](../../docs/fake-server.md#what-llamacpp-sends)):

| Model, Q4_K_M | Download | Alone | Memory | Reasons |
|---|---|---|---|---|
| SmolLM2-135M-Instruct | 105 MB | First token at 6 ms, about 300 tokens/s | 0.3 GiB | No |
| Qwen3.5-0.8B | 533 MB | First token at 126 to 562 ms, 55 to 85 tokens/s | 1.0 to 1.2 GiB | Yes, by default |
| Qwen3.5-2B | 1.28 GB | 32 tokens/s once, 1.2 once: the VM ran short of memory | 1.7 GiB | Yes, by default |

Four requests at once:

| Model | Slots | First tokens at | Each ran at | All done in |
|---|---|---|---|---|
| SmolLM2-135M | 1 | 7, 37, 160 and 361 ms | 310 to 349 tokens/s | 442 ms |
| SmolLM2-135M | 4 | 51 to 131 ms | 107 to 152 tokens/s | 475 ms |
| Qwen3.5-0.8B | 1 | 0.3, 1.6, 5.0 and 6.9 s | 24 to 73 tokens/s | 7.7 s |
| Qwen3.5-0.8B | 4 | 0.7 to 2.5 s | 13 to 20 tokens/s | 5.6 s |

- **Without a slot count,** the server picked 4 on that VM. ai-bootstrap's Compose sets none.
- **Qwen's reasoning chunk** is `{"reasoning_content": "Thinking"}` in the delta, with no `content`, as the fake server sends it ([0023](0023-the-fake-upstream-server-go-in-its-own-module-shaped-as-llama-cpps-chunks.md)).
- **A model's URL alone loads nothing.** With `--model-url` and no `--model`, this build starts in "router mode", with no model. With both, it downloads the file to the path once, and loads it.
- **ai-bootstrap** runs the same server with `-hf`, a Hugging Face repository and a quantization, its default model Qwen3.5-4B, its CORS limited to `localhost`, and a healthcheck on `/health` with 30 minutes to start ([its `compose.yaml`](https://github.com/fkuhne/ai-bootstrap/blob/main/compose.yaml)). Its list of models names Qwen3.5-2B as the smallest that answers well ([its `models.md`](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/models.md)).

## Decision

Compose gets a `llama-cpp` service: llama.cpp's server at build `b12242`, pinned by digest, serving Qwen3.5-0.8B at Q4_K_M with 4 slots and 8,192 tokens of context, on CPU.

- **The model:** `Qwen3.5-0.8B-Q4_K_M.gguf`, 532.5 MB, from [`unsloth/Qwen3.5-0.8B-GGUF`](https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF), licensed Apache 2.0. It's ai-bootstrap's family, and it reasons, so the backends' `reasoning` events carry real chunks.
- **Pinned by its commit.** The server is given the file's URL at the repository's commit `6ab461498e20`, and a path in a Docker volume: it downloads that exact file once, and loads it from there afterwards. Both are settings, `LLAMA_MODEL_URL` and `LLAMA_MODEL_FILE`.
- **4 slots,** written out: what the server picked here, now the same on every machine. Each slot gets a quarter of the context, 2,048 tokens. `LLAMA_SLOTS` and `LLAMA_CONTEXT_SIZE` change them.
- **No image or audio component:** the contract is text only.
- **Only when asked.** It sits in a Compose profile, so `docker compose up` doesn't download a model. `docker compose up -d --wait llama-cpp` starts it, on `127.0.0.1:8020`.
- **A helper, with no limits,** like the fake server. Its own speed isn't what's measured.
- **CORS limited to `localhost`,** as ai-bootstrap does: its port is open to the browsers of this machine only.
- **Its healthcheck is the image's own,** `/health`, which answers 503 while the model loads. The first start has 30 minutes, for the download.
- **A backend reaches it** with `LLM_PROVIDER=openai-compatible` and `LLM_BASE_URL=http://llama-cpp:8080/v1`.
- **Not in CI:** it needs a download, and its answers aren't fixed.
- **The conformance suite checks it apart,** with `docker compose run --rm conformance -m llama_cpp`: each backend answers through it, whole and streamed, with reasoning; passes a parameter on; maps a refusal to 502; and is unready while it's stopped.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| SmolLM2-135M-Instruct | The smallest and fastest, near the fakes' pace. But it doesn't reason, and it's from 2024 |
| Qwen3.5-2B | ai-bootstrap's smallest suggestion, with better answers. But 1.28 GB and more memory, for answers whose quality isn't measured |
| One slot | Every request at full speed, and the queue plain to see. But not how the server usually runs, and a second request waits for the whole first one |
| llama.cpp's automatic slots | Nothing to set. But it may differ from one machine or release to the next (unchecked) |
| `-hf` with a repository and a quantization, as ai-bootstrap | Shorter. But it takes whatever the repository holds that day |
| Always started, with the backends | Simpler to use. But `docker compose up`, and CI, would download 533 MB first |

## Consequences

- The first `docker compose up -d --wait llama-cpp` downloads 533 MB into the `llama-models` volume; `docker compose down --volumes` deletes it.
- The machine needs about 1.2 GiB of memory for it, beside the backends.
- Its answers aren't fixed, so its checks look at shapes, not texts.
- Plan step 2.4 runs the backends against it at low rates. With 4 slots, more than 4 requests at once share the CPU, and a fifth waits.
- Ollama Cloud (plan step 4.2) is reached the same way, with another URL and a key.

## Assumptions to verify

- [x] Each backend answers through llama.cpp, whole and streamed, with reasoning events. To check in this step. *2026-11-10: 21 checks passed, 7 for each backend ([llama.cpp](../../docs/llama-cpp.md)).*
- [x] llama.cpp's refusals map to the contract's errors as [0024](0024-each-backends-upstream-client-its-plain-http-client-one-pool-setting-no-retries.md) says: a 400 becomes 502. To check in this step. *2026-11-10: `"temperature": "hot"` got llama.cpp's 400, and a 502 from every backend, whole and streamed; with llama.cpp stopped, a 503 ([llama.cpp](../../docs/llama-cpp.md)).*
- [x] Compose starts a service that sits in a profile when it's named, in both the Compose outside, 5.5.1, and the one inside the suite's image, 5.1.4. To check in this step. *2026-11-10: both started it by name; `docker compose config --services` doesn't list it otherwise (our runs).*
- [x] The pinned file is downloaded once, and loaded from the volume afterwards, without the network. To check in this step. *2026-11-10: healthy 78 s after the first start, download included; 4.9 s after a later one; and loaded with no network at all ([llama.cpp](../../docs/llama-cpp.md)).*
- [ ] 4 slots and 8,192 tokens fit the machine that makes the report's runs. Unchecked; plan step 6.2.

## Learned while building it

- **The suite's checks through it need llama.cpp started first.** Its first start downloads the model, which takes longer than the suite waits for a service, 60 s. Once the model is in its volume, the checks restart it themselves.

## Sources

- Our runs on the Mac, 2026-11-10: three models, each with 1 and 4 slots, through llama.cpp's server at `b12242`.
- Hugging Face's API for each repository's files, sizes, licence and commit, 2026-11-10.
- `llama-server --help` in the pinned image, and [its README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), read on 2026-11-10.
- ai-bootstrap's [`compose.yaml`](https://github.com/fkuhne/ai-bootstrap/blob/main/compose.yaml), [`compose/llm-cpu.yaml`](https://github.com/fkuhne/ai-bootstrap/blob/main/compose/llm-cpu.yaml) and [`docs/models.md`](https://github.com/fkuhne/ai-bootstrap/blob/main/docs/models.md), read on 2026-11-10.
- [llama.cpp's notes](../../docs/llama-cpp.md), with every run of this step.
- The owner's picks, 2026-11-10.
