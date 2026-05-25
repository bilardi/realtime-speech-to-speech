# Connection pool for `AWSCRTHTTPClient` — supporting documentation

This document is the technical and operational supplement to the issue on `smithy-lang/smithy-python` proposing an opt-in connection pool with lease semantics for `AWSCRTHTTPClient`. It provides:

- The branches in the contributor's repositories referenced by the issue (for code review and reproducibility)
- Setup commands to reproduce each empirical benchmark mentioned in the issue
- The full historical evolution table behind the simplified comparison in the issue body
- Detailed mechanism analysis of the deepcopy interaction

The issue body itself is intentionally concise. This document is where to look for everything beyond the headline argument.

## Branches pushed for this issue

| Repository | Branch | Role |
|---|---|---|
| [`bilardi/smithy-python`](https://github.com/bilardi/smithy-python/tree/add-awscrt-connection-pool) (fork of `smithy-lang/smithy-python`) | `add-awscrt-connection-pool` | Source code of the proposed PR. Single file modified: `packages/smithy-http/src/smithy_http/aio/crt.py` (+248/-24 lines) |
| [`bilardi/amazon-polly-streaming`](https://github.com/bilardi/amazon-polly-streaming) | `feature/smithy-integration` | Reference hand-rolled implementation used in benchmark 1 (`smithy_aws_core[eventstream]` + lease pool over `awscrt`) |
| [`bilardi/realtime-speech-to-speech`](https://github.com/bilardi/realtime-speech-to-speech) | `feature/smithy-polly` | Application code for benchmark 1 |
| `bilardi/realtime-speech-to-speech` | `feature/aws-sdk-polly` | Application code for benchmark 2 (`aws-sdk-polly` vanilla) |
| `bilardi/realtime-speech-to-speech` | `feature/add-awscrt-connection-pool` | Application code for benchmark 3 (`aws-sdk-polly` + proposed PR) |
| `bilardi/realtime-speech-to-speech` | `master` | Application code for benchmark 4 (`amazon-polly-streaming` 1.1.0 from PyPI, pool without smithy stack) |

## Reproducing the benchmarks

**Common methodology**: 3-4 runs of 5 utterances × 2 listeners (en-US + de-DE), 1 Italian speaker. Restart `make serve` between runs to reset pool/cache. Measure `polly_first_byte_ms` (time from "translate done" event to first Polly audio chunk on each listener).

### Benchmark 1: `amazon-polly-streaming` smithy + pool (P50 ~290 ms)

```sh
test -d ~/github/bilardi/claude/amazon-polly-streaming || \
    git clone https://github.com/bilardi/amazon-polly-streaming.git ~/github/bilardi/claude/amazon-polly-streaming
cd ~/github/bilardi/claude/amazon-polly-streaming
git checkout feature/smithy-integration

cd ~/github/bilardi/claude/realtime-speech-to-speech
git checkout feature/smithy-polly
rm -rf .venv
uv sync
uv pip install -e ~/github/bilardi/claude/amazon-polly-streaming
make serve
```

### Benchmark 2: `aws-sdk-polly` vanilla (P50 ~350 ms)

```sh
cd ~/github/bilardi/claude/realtime-speech-to-speech
git checkout feature/aws-sdk-polly
rm -rf .venv
uv sync
make serve
```

### Benchmark 3: `aws-sdk-polly` + proposed PR (P50 ~290 ms)

```sh
test -d ~/github/bilardi/claude/smithy-python || \
    git clone https://github.com/bilardi/smithy-python.git ~/github/bilardi/claude/smithy-python
cd ~/github/bilardi/claude/smithy-python
git checkout add-awscrt-connection-pool

cd ~/github/bilardi/claude/realtime-speech-to-speech
git checkout feature/add-awscrt-connection-pool
rm -rf .venv
uv sync
uv pip install -e ~/github/bilardi/claude/smithy-python/packages/smithy-http
make serve
```

### Benchmark 4: `amazon-polly-streaming` 1.1.0 from PyPI (P50 ~346 ms) — additional context

```sh
cd ~/github/bilardi/claude/realtime-speech-to-speech
git checkout master
rm -rf .venv
uv sync
make serve
```

This benchmark uses the published 1.1.0 release of `amazon-polly-streaming` from PyPI (custom event-stream/signer, no smithy stack, with the connection pool). It is included for context on the smithy-vs-custom event-stream cost difference (~16 ms).

To verify which mode is active in the venv:
```sh
uv pip show amazon-polly-streaming smithy-http 2>&1 | grep -E "^(Name|Editable|Location)"
```

## Full evolution table

The issue body shows a simplified comparison (`aws-sdk-polly` vanilla vs `aws-sdk-polly` + proposed PR). Below is the full evolution across all four benchmarks, for context on the design choices behind the proposal.

| Version | Stack | P50 |
|---|---|---:|
| `amazon-polly-streaming` 0.2.0 | awscrt | ~370 ms |
| `amazon-polly-streaming` 0.3.0 | awscrt + connection pool | ~306 ms |
| `amazon-polly-streaming` `feature/smithy-integration` | smithy + event-stream + pool | ~290 ms |
| `aws-sdk-polly` 0.6.0 vanilla | smithy + event-stream, **no pool** | ~350 ms |
| `aws-sdk-polly` 0.6.0 + proposed PR | smithy + event-stream + pool | ~290 ms |

Key takeaways across the rows:

- Row 1 → 2: the pool alone gains ~64 ms (370 → 306)
- Row 2 → 3: smithy + event-stream layered on top of the pool gains ~16 ms (`smithy_aws_core[eventstream]` is marginally more efficient than the custom implementation that `amazon-polly-streaming` 1.0.0 was using)
- Row 3 → 4: regression of ~60 ms when the right stack (smithy) loses the pool
- Row 4 → 5: the proposed PR restores P50 to the level of row 3

The proposed PR essentially recovers, on top of the official `aws-sdk-polly`, what was already validated in production by `amazon-polly-streaming`'s lease pool.

## Detailed mechanism: why the pool needs to live on `_AWSCRTEventLoop`

The smithy operation pipeline calls `deepcopy(self._config)` on every operation (see `aws-sdk-polly`'s generated `client.py:119`). The `transport` (`AWSCRTHTTPClient`) is part of the config, so it gets deepcopied. `AWSCRTHTTPClient.__deepcopy__` (introduced in PR #355 for plugin-safety) returns a new instance with an empty `_connections` cache.

Practical result: every operation pays a full TLS + ALPN + HTTP/2 setup, ~60 ms of overhead versus warm connection reuse. The author of PR #355 explicitly flagged the risk in the PR body: *"I'm a bit concerned about not sharing the connection pool"*.

A pool placed on the transport instance would be discarded on every operation, same as the current `_connections` cache. The `_AWSCRTEventLoop` is the only object already shared via `__deepcopy__` (which passes `eventloop=self._eventloop` to the new instance), so it is the natural lifetime host for a connection pool that needs to survive operations.

The proposed PR uses lazy initialization: `_AWSCRTEventLoop.pool` is `None` until the first `send()` whose config has `connection_pool` set. Zero cost for users who don't opt in.

## Cross-references

- `realtime-speech-to-speech` repo root: <https://github.com/bilardi/realtime-speech-to-speech>
- `amazon-polly-streaming` on PyPI: <https://pypi.org/project/amazon-polly-streaming/>
- `bilardi/smithy-python` fork branch: <https://github.com/bilardi/smithy-python/tree/add-awscrt-connection-pool>
- Related smithy-python PR [#355](https://github.com/smithy-lang/smithy-python/pull/355) (*Safely copy crt clients*): introduces the `__deepcopy__` interaction
- Related smithy-python issue [#657](https://github.com/smithy-lang/smithy-python/issues/657) (*`await_output()` hangs forever on HTTP 429*): same use case (Nova Sonic bidirectional fan-out hitting per-connection stream limits)
