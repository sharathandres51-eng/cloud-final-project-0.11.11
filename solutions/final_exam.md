# Final Exam — Theoretical Questions

## 3.1 API Design

### Question 1

The `POST /diagnose` request schema has exactly **7 fields**:

1. `piece_id` (string) — unique identifier, echoed back in the response
2. `die_matrix` (int) — the matrix key used to look up reference times
3. `lifetime_2nd_strike_s` (float, nullable) — cumulative time to 2nd strike
4. `lifetime_3rd_strike_s` (float, nullable) — cumulative time to 3rd strike
5. `lifetime_4th_strike_s` (float, nullable) — cumulative time to 4th strike
6. `lifetime_auxiliary_press_s` (float, nullable) — cumulative time to auxiliary press
7. `lifetime_bath_s` (float, nullable) — cumulative time to bath

**Why cumulative input is the right choice:** The PLCs on the forging line record absolute timestamps as the piece reaches each stage, not inter-stage durations. Sending cumulative values keeps the API honest to what the sensors actually produce — no pre-processing happens on the client side, which means the diagnosis is always derived from the raw source of truth. It also avoids the data-consistency risk of receiving pre-computed partials that were derived with a different (possibly buggy) formula than the one the exam specifies in §1.5.

Just as importantly, a single missing cumulative timestamp has a deterministic, documented effect: it nullifies the two adjacent partial times (the one that terminates at it and the one that starts from it). This is covered in my `test_middle_null_nullifies_two_adjacent_segments` test. If the client sent partial times directly, we would have no way to distinguish "sensor was missing" from "partial was deliberately set to null" — the null-propagation semantics would be lost.

**Why this is the minimum necessary set:** The response in §1.4 needs `piece_id` (echoed), `die_matrix` (to select the reference row from `reference_times.json`), and the 5 timing values (to derive the 5 partial times in `segments[]`). Dropping any field breaks the contract: no `piece_id` → response can't be matched back to the caller; no `die_matrix` → no reference lookup; missing any `lifetime_*_s` is already supported via nullable fields but dropping the field from the schema entirely would prevent the null-propagation semantics in §1.5. No additional fields are needed — `probable_causes` is looked up from the hardcoded cause table in `src/diagnose.py` based on which segments are penalized, not from any client input.

### Question 2

Loading `reference_times.json` once at startup (in `src/app.py`, via the module-level `REFERENCE_TIMES = json.load(...)` call before FastAPI is instantiated) is the right approach for three reasons that matter in a containerized deployment.

**First, performance.** Every `POST /diagnose` call finishes in single-digit milliseconds of pure CPU work — five subtractions and five comparisons. If I re-read the JSON file on every request, disk I/O would easily dominate the total latency, especially under concurrent load on Fargate where each request competes for the same inode. Reading a ~700-byte file 1,000 times per minute is silly when the content never changes during the container's lifetime.

**Second, immutability matches the container model.** The reference times are baked into the image at build time via `COPY reference_times.json ./reference_times.json` in the Dockerfile. The file cannot change without a rebuild and redeploy. That means re-reading it on every request can never produce a different result — it's pure waste. This mirrors the 12-factor principle of treating build-time artifacts as immutable.

**Third, it surfaces configuration errors at startup, not at first request.** If the JSON is malformed or missing, the container fails to start and ECS will flag the task as unhealthy immediately. If I deferred the read until the first `POST /diagnose`, a broken reference file would only surface when the first user actually tried to diagnose a piece — a much worse failure mode because it looks like a runtime bug instead of a deployment problem.

The tradeoff: updating reference times requires a rebuild + redeploy. That is acceptable because reference medians are computed from historical production data, not tuned by operators at runtime.

## 3.2 Containerization And Deployment

### Question 1

My `api/Dockerfile` is deliberately minimal:

```dockerfile
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn>=0.32.0" \
    "pydantic>=2.9.0"

COPY src/ ./src/
COPY reference_times.json ./reference_times.json

ENV PYTHONPATH=/app
EXPOSE 80

CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "80"]
```

**`FROM python:3.13-slim`** — Python 3.13 matches the version required by the exam (§2). The `slim` variant is about 10× smaller than the default Debian-based image (150 MB vs 1 GB+) because it strips out build tools, docs, and locale data. For a single-purpose API that only needs the Python runtime plus three pinned packages, `slim` is the right tradeoff: small image = fast ECR pulls = fast Fargate task starts.

**`WORKDIR /app`** — sets a consistent working directory so subsequent `COPY` paths are predictable and the `CMD` entrypoint runs from a known location.

**`RUN pip install --no-cache-dir ...`** — installs only the three runtime dependencies inline (FastAPI, Uvicorn, Pydantic). I deliberately skipped installing `pytest` and `httpx` from the `dev` group in pyproject.toml because those are test-only — not shipping them keeps the image smaller and reduces the attack surface. `--no-cache-dir` prevents pip from caching wheel files in `/root/.cache`, shaving more bytes off the final layer.

**`COPY src/ ./src/` and `COPY reference_times.json ./reference_times.json`** — ship only what the runtime needs. The `tests/`, `generate_validation.py`, `validation_pieces.csv`, `validation_expected.json`, and `pyproject.toml` are deliberately excluded — they're development artifacts, not runtime requirements. This also makes the image reproducible: no dev-only files leak into production.

**`ENV PYTHONPATH=/app`** — lets `uvicorn src.app:app` resolve the `src` package without needing a formal pip install step.

**`EXPOSE 80`** — documents the port for human readers and for tooling; the exam requires the API to be reachable on TCP from Fargate's public IP, and port 80 avoids an extra port mapping.

**`CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "80"]`** — runs uvicorn bound to all interfaces (required inside a container; binding to `127.0.0.1` would make the port unreachable from outside the container network namespace). Using the exec form (JSON array) ensures uvicorn receives signals directly from PID 1 so ECS task shutdown is clean.

### Question 2

Two other AWS compute options that could host this API, each with a concrete tradeoff against my Fargate choice:

**Option A — AWS Lambda + API Gateway.** Lambda would run the `diagnose()` function (or the whole FastAPI app via Mangum) on-demand, billed per request. **Advantage:** true scale-to-zero — for a forging-line diagnostics API that may be used sporadically during a shift, I would pay nothing during idle hours, whereas my Fargate task is billed per instance-hour 24/7. **Disadvantage:** cold starts. The first request after idle would incur ~500 ms to 2 s of container init latency, which is a bad experience for an operator trying to diagnose a stuck piece on the line. Fargate stays warm, so every request finishes in single-digit ms.

**Option B — Amazon EC2 with a self-managed Docker host.** I could run the same image on a `t3.small` EC2 instance. **Advantage:** cheaper per hour at sustained load — a `t3.small` costs around $15/month vs ~$30/month for an always-on Fargate task with equivalent CPU/memory, because Fargate includes the orchestration overhead in the price. **Disadvantage:** I would own the OS — patching the kernel, managing disk space, rotating SSH keys, configuring a reverse proxy in front of uvicorn, writing a systemd unit. Fargate abstracts all of that; I only ship the image and the task definition. For a small API, the operational savings of Fargate easily outweigh the extra hourly cost.

## 3.3 Testing And Extensibility

### Question 1

The exam asks me to test `diagnose()` as a pure function rather than through HTTP because the two test targets have fundamentally different concerns.

`diagnose()` is where the **business logic** lives — the §1.3 rule table, the null-propagation semantics, the cause lookup. Testing it directly means I can write 43 test cases that finish in 0.07 seconds (`pytest tests/ -v` output) and cover the logic exhaustively — every matrix × every segment × every boundary condition (deviation = 1.0, deviation = 5.0, negative deviation, anomaly > 5.0, multi-segment, null propagation). No HTTP server has to start, no port has to be bound, no serialization has to happen. The test suite is something I can run on every save without friction.

Testing through HTTP would instead exercise **the framework** — Pydantic validation, FastAPI request parsing, the JSON serializer, uvicorn's request dispatch. These are all Sebastián Ramírez's code, not mine. If a test fails after an HTTP round trip, I would not know whether I broke the logic or misused the framework. Framework bugs are not my job to catch; my job is to ensure the diagnosis rules are correct.

There is a practical separation benefit too: because `diagnose()` takes a plain dict and returns a plain dict, it is trivially reusable outside the web context. The same function could later be called from a batch job that processes a parquet file directly, or from a Kafka consumer that applies the rule to streaming PLC events — without any HTTP layer involvement. Writing the test against the dict-in/dict-out contract is what forces that clean separation. Coupling the test to HTTP would push me toward coupling the logic to HTTP too, which is exactly what the -10 pts "logic coupling" penalty is designed to prevent.

The FastAPI route in `src/app.py` is reduced to three lines: dump the Pydantic model to a dict, call `diagnose()`, return the result. Nothing worth unit-testing separately lives in the route.

### Question 2

Adding a new die matrix `6001` touches four layers. Here is every change:

**1. Data file — `api/reference_times.json`.** Add a new top-level key `"6001"` with the five segment medians computed from production data for that matrix. In my implementation this means re-running the same median calculation I used in the first place:

```python
sub = df[df['die_matrix'] == 6001]
ref["6001"] = {seg: round(float(sub[col].median()), 2) for seg, col in partial_cols.items()}
```

**2. Code — no change.** Because `diagnose()` in `src/diagnose.py` reads `reference_times` as a dict passed in at startup, it does not hardcode the list of matrices anywhere. The lookup `reference_times[matrix_key]` just works for any new key. The cause table in `CAUSE_TABLE` is keyed by segment (not by matrix), so it also needs no change — the same five segments apply to all matrices. This is the payoff of the config-driven design.

**3. Tests — `api/tests/test_diagnose.py`.** Update the `MATRICES` list at the top of the file from `["4974", "5052", "5090", "5091"]` to `["4974", "5052", "5090", "5091", "6001"]`. Because my main test functions use `@pytest.mark.parametrize("matrix", MATRICES)`, the parametrize engine automatically generates the 6 scenarios (all-OK + 5 penalized) for the new matrix — that's 6 new tests for free. The test count goes from 24 to 30 required matrix-scenario tests, with no new test code written. I should also regenerate the validation set to include a piece for matrix 6001 if the exam's coverage map were updated — but that's a one-line change in `generate_validation.py` and a re-run of the script (never hand-edited).

**4. Redeployment.** The Dockerfile copies `reference_times.json` into the image at build time. So after updating the JSON file, I would:

- `docker build --platform linux/amd64 -t diagnose-api .`
- `aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.eu-west-1.amazonaws.com`
- `docker tag diagnose-api:latest <account>.dkr.ecr.eu-west-1.amazonaws.com/diagnose-api:latest`
- `docker push <account>.dkr.ecr.eu-west-1.amazonaws.com/diagnose-api:latest`
- `aws ecs update-service --cluster <cluster> --service diagnose-api-service --force-new-deployment --region eu-west-1`

ECS will drain the old task and spin up a new one pulling the updated image. During the rollover, the old container still answers `POST /diagnose` for the existing 4 matrices — only requests for matrix 6001 would receive the "unknown die_matrix" 400 error until the new task is healthy. No database migrations, no downtime, no client-side change required.
