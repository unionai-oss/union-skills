---
name: union-sdk-plugin
description: 'Author Union.ai workflows that use the Union SDK plugin, flyteplugins.union — persistent mountable Volumes (RWVolume/ROVolume/BlockVolume/allow_volumes), artifact factories (source/build/serve/materialize/on), ssh-into-task debug and run forking (debug/fork/with_debugcontext/with_forkcontext), and remote control-plane objects (ApiKey, Cluster, ClusterPool, Queue, Metrics, SSHDebug, SystemLogs). Use for "Union plugin", "factories", "materialize", "Volume", "fork a run", "ssh into a task", "debug a run", "Union ApiKey", or "Union plugin source".'
---

# Union SDK plugin (`flyteplugins.union`)

Union.ai layers a proprietary plugin, `flyteplugins.union`, on top of the open-source
`flyte` SDK. It is Union's extension surface: the things you can say to a Union platform
that plain Flyte cannot express. Four modules, each a distinct capability:

| Module | What it is |
|---|---|
| [`flyteplugins.union`](https://www.union.ai/docs/v2/union/api-reference/union-plugin/flyteplugins.union.md) | ssh-into-task **debug** and run **fork**: `debug`, `fork`, `with_debugcontext`, `with_forkcontext`. |
| [`flyteplugins.union.io`](https://www.union.ai/docs/v2/union/api-reference/union-plugin/flyteplugins.union.io.md) | Persistent, **mountable Volumes** backed by object storage (`RWVolume`, `ROVolume`, `BlockVolume`, `ROBlockVolume`). |
| [`flyteplugins.union.factory`](https://www.union.ai/docs/v2/union/api-reference/union-plugin/flyteplugins.union.factory.md) | Declared **factories** of partitioned artifacts the platform materializes on demand. |
| [`flyteplugins.union.remote`](https://www.union.ai/docs/v2/union/api-reference/union-plugin/flyteplugins.union.remote.md) | Union **control-plane objects**: `ApiKey`, `Cluster`, `ClusterPool`, `Queue`, `Role`, `Metrics`, `SSHDebug`, `SystemLogs`, `VolumeExplore`. |

Docs: <https://www.union.ai/docs/v2/union/api-reference/union-plugin/>

This is **authoring** — writing and launching Union workflows. It is a different job from
getting a deployment up, which the setup skills (`union-provision-aws`,
`union-connect-cluster`, `union-debug-cluster`) cover. Reach for this skill when the
*code*, not the cluster, is the subject: the user wants to fork or debug a run, version
data as a Volume, declare a factory of artifacts, or drive a Union control-plane object.

Every call below that launches a remote run or creates a persistent remote object is an
⛔ **APPROVAL GATE** — runs cost compute on the cluster, and admin objects outlive the
session. Read-only queries (`listall`, `get`, `graph`, `validate`, metrics) are
🟢 READ-ONLY. **Diagnose before you mutate**, exactly as everywhere else in these skills.

## What you need first

The plugin ships with the Union platform and is baked into the driver and task images it
runs. To *author* against it you need the `flyte` SDK 2.x configured and signed in to the
Union organization — the same setup as `union-run-locally` steps 1–3. The plugin's remote
calls honour the same `.flyte/config.yaml` and cached credential. Nothing here is
AWS-specific and it uses none of the setup skills' state-file conventions — the plugin
talks to the platform, not to cloud resources.

Confirm the slim dependencies resolve and the org answers before writing plugin code:

```python
import flyte
import flyteplugins.union  # raises ImportError if the plugin isn't in this env
from flyteplugins.union import factory, io, remote

print("flyte", flyte.__version__)
```

```bash
flyte get project   # 🟢 READ-ONLY — proves config + login, and lists the default project
```

If `flyteplugins` does not import, the environment is missing the plugin — install the
`flyteplugins-union` distribution into the venv (or, when iterating on an *unreleased*
build, layer the locally-built wheel with `io.with_local_flyteplugins` /
`utils.with_local_flyteplugins_union`). Then re-check.

---

## 1. ssh-into-task debug and run forking

Two ways to replay or inspect a run, both Union-only. They are the practical heart of
"something went wrong inside a task" — look at the live pod, or rerun with a fix.

### Debug into a live task

`debug()` launches a task (or relaunches an existing run) with an ssh daemon injected, so
you can `ssh` in and poke at the running action. Two forms, mirroring `flyte.run` /
`flyte.rerun`:

```python
import flyte
from flyteplugins.union import debug
from flyteplugins.union.remote import SSHDebug

# 1. launch a task with ssh-debug enabled
run = debug(train_task, epochs=20)

# 2. OR relaunch a prior run in debug mode; change an input, keep the rest
run = debug("ul56wcvgqrb9vzhzz5l2", inputs={"epochs": 5})

# connect — polls until the :6060 IDE route is up, then prints a working ssh-config
SSHDebug.connect(run.name)
```

Then `ssh flyte-debug` (the default `host_alias`) into the running action. The CLI form,
`flyte debug RUN_NAME`, relaunches *and* connects in one shot — handiest for interactive
use. Lower level: `with_debugcontext()` is `flyte.with_runcontext` preconfigured with the
ssh env, so `.run(task, ...)` / `.rerun(run, ...)` work as usual and `SSHDebug.launch_env()`
gives you the env vars for a hand-rolled launcher.

The debug identity is managed for you: `ensure_keypair()` creates and reuses
`~/.flyte/ssh-debug/id_ed25519`, and `ensure_api_key()` provides headless auth that does not
expire mid-session. No manual key handling.

⛔ **APPROVAL GATE** — `debug()` and `flyte debug` launch a fresh run on the cluster (image
build + compute).

### Fork a run with new code and/or inputs

`fork()` replays a run: its succeeded actions are **reused** (cache-like), and the actions
whose code you replaced re-execute along with anything downstream of them. Unchanged inputs
keep the source run's values; pass keyword inputs to override the root action's parameters.

```python
from flyteplugins.union import with_forkcontext

run = with_forkcontext(
    name="fix-1",  # any flyte.with_runcontext option applies
    env_vars={"LOG_LEVEL": "debug"},
    queue="gpu",
).fork("ul56wcvgqrb9vzhzz5l2", task_template=fixed_task)
```

`with_forkcontext()` returns a runner like `flyte.with_runcontext` plus `fork()`; its
keyword arguments are `flyte.with_runcontext`'s one-for-one (`name`, `project`, `domain`,
`queue`, `env_vars`, `labels`, `interruptible`, `overwrite_cache`, `raw_data_path`, ...), so
anything you can set on a run you can set on a fork. What to fork — run name, substitute
code, forced replays — belongs to `fork()` itself:

- `force_rerun_actions=[...]` — names of actions that must re-execute even though they
  succeeded in the source run. Use to invalidate a buggy cached step and re-derive its
  subtree.
- `allow_missing_source_outputs=True` — proceed when the source run's outputs were cleaned
  out of storage, reading its inputs URI directly.

⛔ **APPROVAL GATE** — a fork is a remote run.

---

## 2. Volumes — persistent mountable data

`flyteplugins.union.io` adds a `Volume` type that materializes as a real mountable
filesystem inside a task pod, backed by an **object-store bucket** (immutable data chunks)
plus a **metadata index** (a SQLite `.db` or Redis `dump.rdb`, chosen by
`metadata_store_type`). The index rides through the normal Flyte literal system as a
Pydantic model, so lineage, caching, fork and clone are first-class — that is the point:
state that persists across runs and is cheap to fork instead of re-materializing.

Types and the lifecycle:

| Type | Role |
|---|---|
| `RWVolume` | Mutable working copy. `RWVolume.new(name=...)` creates one; write under it; snapshot it with `commit()` (keeps it writable) or `finalize()` (unmounts and publishes). |
| `ROVolume` | Immutable, versioned snapshot — what `commit()`/`finalize()` return, and what a *downstream* task receives. `read_only` mounts. |
| `BlockVolume` / `ROBlockVolume` | Writable / immutable volumes whose content is a single ext4 filesystem image (`is_block`). For block-device-shaped data. |
| `Volume` | The base: any version or handle, identified by its metadata index. |

A task that builds a volume, then hands an immutable version onward — the checkpoint pattern
(`commit()` per epoch, return the last `ROVolume`):

```python
import flyte
from flyteplugins.union.io import (
    RWVolume,
    ROVolume,
    with_high_throughput_volume_deps,
)

env = flyte.TaskEnvironment(
    name="volume-train",
    image=with_high_throughput_volume_deps(flyte.Image.from_debian_base()),
    pod_template=flyte.PodTemplate().allow_fuse(),
)


@env.task
def train() -> ROVolume:
    ckpt = RWVolume.new(name="model-ckpts")
    mnt = ckpt.mount()  # returns a Path to the mounted filesystem
    for epoch in range(10):
        # ... train and write checkpoints under mnt ...
        versions = ckpt.commit(message=f"epoch {epoch}")  # ROVolume; handle stays writable
    return ckpt.finalize(message="done")
```

Because `commit()` drains writeback before snapshotting, the returned `ROVolume` references
durable chunks and is safe to pass to a downstream task. Returning an `RWVolume` from a task
triggers the automatic `finalize()` path. `fork()` on a volume branches it into an
independent copy that shares chunks until one side writes — the cheap, lazy clone.

### Making the mount work: image and pod template

Every mount needs both of the following, or it fails at the first `mount()`:

- **`fuse3` in the image.** JuiceFS execs the `fusermount3` helper to mount; the default
  minimal images do not ship it, so the client exits with `fuse: fuse is not installed`. Add
  it with `image.with_apt_packages("fuse3")`, or use `with_high_throughput_volume_deps()`,
  which installs `fuse3` *and* (for the Redis store) `redis-server` / `redis-tools`, and
  sets `UNION_VOLUME_METADATA_STORE=redis` so volumes default to Redis without repeating the
  keyword each time.
- **`pod_template=flyte.PodTemplate().allow_fuse()`** on the `flyte.TaskEnvironment`, which
  grants `/dev/fuse` and the capability an unprivileged mount needs.

### `allow_volumes()` — zero-privilege brokered mounts

If the cluster runs the data plane's mount **broker** (`uvolMountBroker` DaemonSet +
`CSIDriver`), `io.allow_volumes(pod_template=...)` is the alternative to `allow_fuse()`: the
broker **premounts** the FUSE channel and the in-pod JuiceFS client *adopts its file
descriptor* over a socket, so the pod performs no `mount(2)` and needs **no capabilities, no
`/dev/fuse`, and no `hostPath`**. `Volume.mount` auto-detects the channel via
`$UVOL_CHANNEL_DIR`. The broker path is what lets a task keep whatever identity and
capabilities it would otherwise run with.

```python
env = flyte.TaskEnvironment(
    name="volume-train",
    image=with_high_throughput_volume_deps(flyte.Image.from_debian_base()),
    pod_template=io.allow_volumes(),  # needs the uvolMountBroker on the data plane
)
```

`allow_volumes` also takes `cache_size=`, `cache_dir=`, and `shared_node_cache=True` (a
per-*namespace* node-shared chunk cache, so pods on one node fetch each chunk from object
storage once per node instead of once per pod). These tune throughput; the two runtime
requirements above are the floor.

### Reading data back on the platform

`flyteplugins.union.remote.VolumeExplore` resolves a Volume-typed value on an action and
lets you walk its lineage (`from_action`, `parent`, `lineage`, `provenance`,
`download_index`) — how the UI shows volume lineage, useful to a task that must inspect a
Volume without mounting it. 🟢 READ-ONLY.

---

## 3. Factories — declared artifact graphs

`flyteplugins.union.factory` lets you declare a graph of **partitioned artifacts** — a
factory — that the platform *materializes on demand* (backfill over a date range, or when a
source gets a new version). Tasks are referenced but unchanged; the factory wires them
together and deploys as an ordinary task of type `factory`.

Declaration verbs: `source()` (an artifact made outside the factory), `build()` (name the
artifacts one task call makes), `serve()` (end an app), then `Factory(...)` + `deploy()`.
Nothing runs until `materialize()`.

```python
from flyte.remote import Task
from flyteplugins.union import factory

clean = Task.get("ingest.clean", auto_version="latest")
report = Task.get("analytics.report", auto_version="latest")

raw = factory.source("raw_events")  # type + partitions read from the registry
events = factory.build("events").using(clean, raw=raw, min_quality=30)
daily_report = factory.build("daily_report").using(report, events=events.all("region"))

analytics = factory.Factory("analytics", daily_report)
analytics.deploy()  # ⛔ APPROVAL GATE — registers a task of type factory
run = analytics.materialize(
    daily_report, date="2026-08-01..2026-08-31"
)  # ⛔ APPROVAL GATE — launches a run
```

Key mechanics:

- **Build outputs** line up with the task's return tuple, left to right; `"_"` skips an
  output that is not an artifact: `model, metrics = factory.build("_", "model", "metrics",
  "_").using(train, data=features)`.
- **Partitions are identity** in the registry. `factory.source(name)` needs no `type=` or
  `partitions=` when the registry already fixed them with the artifact's first version
  (deploy reads them back). `factory.partition("date")` passes the instance's value of a
  dimension into a task parameter.
- **`on()` triggers** materialize when a source gets a new version, or on a schedule:
  `factory.on(images)` scores each new day; `factory.on(flyte.Cron("0 3 * * *"), api)`
  retrains nightly; `lag=factory.TimeRange(days=1)` moves the window back.
- **`serve()`** ends a factory in a running app, binding each parameter to an artifact:
  `endpoint = factory.serve("qwen3-chat").using(chat_app, model_path=approved)`. Materializing
  deploys the app with each parameter set to the artifact version it resolved; an app whose
  spec did not change is left alone.
- **`materialize(...)`** pins behavior: `versions={"tracks": "v2"}` reads a source at a pinned
  version instead of latest (and reads a built artifact at a version instead of *building* it
  — how an endpoint is rolled back); `rebuild_all=True` / `rebuild=[...]` / `downstream`
  control what re-executes; `plan_only=True` previews the plan.

🟢 READ-ONLY before committing: `analytics.validate()`, `analytics.graph()` (Mermaid), and
`analytics.deploy(dryrun=True)` all check the graph against the registry and deployed tasks
without registering. Then ⛔ **APPROVAL GATE** for `deploy()` and each `materialize()`.

---

## 4. Remote control-plane objects

`flyteplugins.union.remote` mirrors the `flyte.remote` object pattern for Union-specific
control-plane entities. All follow `listall()` / `get()` / `create()` / `update()` /
`delete()` where relevant.

**API keys** — long-lived client credentials for CI and headless auth:

```python
from flyteplugins.union.remote import ApiKey

keys = ApiKey.listall()  # 🟢 READ-ONLY
key = ApiKey.create(name="my-ci-key")  # ⛔ APPROVAL GATE — creates a credential
print(key.client_id)
# key.client_secret is a secret — route it to a store, never echo it  🔐 SECRET
ApiKey.delete(client_id="my-client-id")  # ⛔ APPROVAL GATE — destructive
```

**Metrics** — pod metrics of a task's action attempt or of an app:

```python
from flyteplugins.union.remote import Metrics

for result in Metrics.get_for_action(run_name="my-run"):  # 🟢 READ-ONLY
    for series in result.series:
        print(result.name, series.labels, series.latest)

Metrics.get_for_app(name="my-app", metrics=["app_requests"])  # 🟢 READ-ONLY
```

**Admin / ops objects** — `Cluster`, `ClusterPool`, `Queue`, `Role`, `Policy`, `User`,
`Member`, `Assignment`. These manage the same entities the setup skills create through the
UI, so **prefer the setup skills for onboarding**, and reach for these to script the
day-to-day: list clusters, drain a queue, inspect a pool's config. Creating or deleting any
of them is ⛔ APPROVAL GATE (a `Queue.create`, a `Cluster.delete`, an `Assignment.create`),
and reading is 🟢 READ-ONLY.

**Runtime visibility** — `SystemLogs.tail()` streams the logs of the Union system components
running on a cluster's data plane, and `SSHDebug` (see §1) resolves the ssh connection into a
running debug action.

Routing: if the user is trying to **provision or connect** infrastructure, that is
`union-provision-aws` / `union-connect-cluster` territory, and the remote object is a thin
programmatic mirror — do not reinvent the IAM/agent flow through `Cluster.create`. If they
want to **inspect or script** the control plane (keys, queues, metrics, system logs),
this is the module.

---

## Choosing — quick map

| User intent | Reach for |
|---|---|
| Inspect what's wrong inside a running task | `debug`, `SSHDebug.connect`, `flyte debug RUN_NAME` |
| Rerun a workflow with a code fix, reusing good results | `fork` / `with_forkcontext` |
| Persist data across runs, versioned and forkable, as a real filesystem | `io.Volume` (`RWVolume.new`, `commit` / `finalize`, `ROVolume`) |
| Declare an artifact pipeline the platform backfills and triggers | `factory.source/build/serve` + `Factory(...).deploy()` + `materialize()` |
| Script Union control plane (keys, clusters, queues, metrics, logs) | `remote.ApiKey` / `Cluster` / `Queue` / `Metrics` / `SystemLogs` |

## Gotchas

- **The plugin is Union-only.** `flyteplugins.union` will not import against open-source
  Flyte. Confirm the org is a Union one before diagnosing an ImportError as an install bug.
- **A `fuse: fuse is not installed` mount failure is an image problem, not a Volume bug.** Add
  `fuse3` (`with_apt_packages`, or `with_high_throughput_volume_deps`).
- **`allow_volumes()` needs the mount broker** on the data plane; `allow_fuse()` does not. On
  a plain self-managed cluster where the broker is not guaranteed, default to
  `flyte.PodTemplate().allow_fuse()`.
- **Fork reuses succeeded actions.** If a cached action is the bug, name it in
  `force_rerun_actions` — otherwise the fork replays the bad result.
- **`debug()` and `fork()` are remote runs** that cost compute; `fork` is remote-only, so a
  non-remote mode is rejected at launch.
- **API keys are credentials.** `ApiKey.create` returns a `client_secret`; treat it like any
  other secret (🔐 SECRET — not in a transcript or commit). Rotate by delete + recreate.
- **Let the type transformer drive publication.** Return the `ROVolume` from a `commit()`, or
  an `RWVolume` to trigger `finalize()`; do not hand-roll unmount/publish.

## Next

- Authoring a tracked run locally first → `union-run-locally`.
- The factory graph visually → `analytics.graph()` before you deploy.
- Control-plane admin the UI already automates for onboarding → the setup skills
  (`union-provision-aws`, `union-connect-cluster`) rather than raw `Cluster.create`.
