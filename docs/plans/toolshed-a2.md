# Toolshed, Plan A2: A New Tool's Package Is Born Public Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new tool's package is created public, linked to the shed, by the shed's own workflow, so that no one ever opens a package's settings by hand: `scripts/push` seeds the package through `seed.yml` the first time a tool is pushed, then pushes the candidate with the contributor's own credential as today.

**Architecture:** GitHub fixes a package's visibility at creation from the credential that creates it; a package created by a workflow's `GITHUB_TOKEN` in a public repository is public and linked to that repository, inheriting its permissions, so any member with write access can push to it afterwards with their own token. `seed.yml` (`workflow_dispatch`, `GITHUB_TOKEN` only) pushes a one-file placeholder tagged `seed` under the tool's name and does nothing when the package exists. `scripts/push` asks the registry anonymously whether the package can be read; when it cannot, it dispatches `seed.yml` with `gh`, waits for the `seed` tag to be readable, and then pushes the candidate. Building, testing, the record, `check`, and `promote` do not change: CI still never builds or runs a tool image.

**Tech Stack:** GitHub Actions on hosted runners (docker, preinstalled), `gh`, bash, the stdlib `check.py`.

**Spec:** `docs/DESIGN.md` §2 (the registry paragraph and the workflow list) and §7, as this plan amends them in Task 3. flyloft's side (`docs/design/toolshed.md` §5 in the flyloft repository) drops its `private` build state in a task of its own once this lands.

## Global Constraints

- Nothing in `scripts/` or `.github/` names the lab: the registry and the repository come from `git remote get-url origin` locally and from `GITHUB_REPOSITORY` in CI, lowercased.
- The only credential `seed.yml` has is `GITHUB_TOKEN` with `permissions: contents: read, packages: write`. It never checks out the repository and never runs a Containerfile.
- A tool's name is `^[a-z0-9]+(-[a-z0-9]+)*$` (the `NAME` regex in `check.py`); `seed.yml` refuses anything else before logging in.
- The placeholder is `FROM scratch` with one file, tagged `<name>:seed`. The tag stays in the package forever; it is not a version (`check.py`'s version rule reads `MAJOR.MINOR.PATCH` tags only) and `promote` never touches it.
- `scripts/push` seeds only when the package cannot be read anonymously; a package that can be read is pushed to directly. A dispatch `gh` refuses (no `gh` login, no access) is printed and the push goes on, so a legacy private package still ends in today's exit 3 with the settings link.
- `gh` must be signed in for the contributor: on a laptop `gh auth login` (the `repo` scope `gh` asks for is enough to dispatch a workflow); on flyloft's host, `GH_TOKEN` in the environment of the build process (flyloft's change, not this plan's).
- The seed wait is at most 5 minutes, polled every 5 seconds; a timeout is printed and the push goes on.
- Tests: `python3 -I -m unittest discover tests` stays green; the new behavior is pinned in `tests/test_scripts.py` with the existing fakes (a fake `gh` joins the fake `podman` and `srun`).
- Commit message style as the repository's: one sentence stating the behavior.

## Review Focus

1. **A tool whose package already exists and is public (every tool published so far):** `scripts/push` never dispatches `seed.yml`; the push is exactly today's. Test in Task 2.
2. **A legacy package created by a PAT and still private:** the dispatch runs, the seed fails or does nothing readable, the wait times out or `gh` refuses, and the push ends in exit 3 with the settings link as today. Test in Task 2 (`gh` refused); the timeout is wall-clock and is left to the live check.
3. **A name `seed.yml` must refuse:** `Web_Scraper`, `../x`, an empty string: refused before any registry call. Checked by hand in Task 4's dispatch of a bad name.
4. **Two contributors pushing the same new name at once:** both dispatch; the second seed finds the package and does nothing; both pushes succeed. No test; the seed job is idempotent by construction.
5. **A fork's pull request:** `seed.yml` has no `pull_request` trigger and `workflow_dispatch` needs write access to the repository, so a fork can never create a package here.

---

### Task 1: `seed.yml` creates a tool's package, public and linked

**Files:**
- Create: `.github/workflows/seed.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: seed

# Creates ghcr.io/<owner>/<repo>/<tool> with a one-file placeholder tagged `seed`. Because this
# repository's GITHUB_TOKEN creates it, the package is public and linked here, inheriting this
# repository's permissions, so a member then pushes the real candidate with their own token
# (scripts/push dispatches this and waits). Nothing here checks out the repository or runs a
# Containerfile: the placeholder is FROM scratch and one file.

on:
  workflow_dispatch:
    inputs:
      tool:
        description: "The tool's name, as its directory under tools/"
        required: true

permissions:
  contents: read
  packages: write

env:
  REGISTRY: ghcr.io

defaults:
  run:
    shell: bash

jobs:
  seed:
    runs-on: ubuntu-latest
    env:
      TOOL: ${{ inputs.tool }}
    steps:
      - run: |
          [[ "$TOOL" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || { echo "::error::'$TOOL' is not lowercase words joined by hyphens"; exit 1; }
      - env:
          TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: docker login "$REGISTRY" -u "$GITHUB_ACTOR" --password-stdin <<< "$TOKEN"
      - run: |
          image="$REGISTRY/${GITHUB_REPOSITORY,,}/$TOOL"
          if docker manifest inspect "$image:seed" > /dev/null 2>&1; then
            echo "$image exists; nothing to do"; exit 0
          fi
          mkdir seed && cd seed
          echo "a placeholder: the tool's images are pushed by whoever builds them" > README
          printf 'FROM scratch\nCOPY README /README\n' > Dockerfile
          docker build -q -t "$image:seed" .
          docker push "$image:seed"
          echo "created $image, public and linked to $GITHUB_REPOSITORY" >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/seed.yml
git commit -m "A new tool's package is created public and linked by the shed's own seed workflow"
```

### Task 2: `scripts/push` seeds a package it cannot read, then pushes

**Files:**
- Modify: `scripts/check.py` (one more mode), `scripts/push`
- Test: `tests/test_scripts.py`, `tests/test_check.py`

**Interfaces:**
- `python3 -I scripts/check.py --published tools/<name>`: the package's tags, one per line, exit 0; exit 4 when the package cannot be read anonymously (missing or private). Registry from `--registry` or the origin remote, as `--resolve`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_scripts.py`: a fake `gh` beside `podman` and `srun` (the same `FAKE_RUNNER`); `FAKE_CHECK` gains `--published`: it prints `seed` and exits 0 when `FAKE_PUBLIC` is set or when the fake log already holds a `workflow run seed.yml` line (the seed happened), else exits 4 with the message. Then:

```python
    def test_push_seeds_a_new_tools_package_then_pushes(self):
        r = self.run_script("push", "t")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log(), ["workflow run seed.yml -R owner/repo -f tool=t", "push ghcr.io/owner/repo/t:src-abc"])
    def test_push_of_a_public_candidate_does_not_seed(self):
        r = self.run_script("push", "t", FAKE_PUBLIC="1")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.log(), ["push ghcr.io/owner/repo/t:src-abc"])
    def test_push_says_when_the_package_is_private(self):
        # gh refuses the dispatch (no login, or a legacy package this repository cannot write): the push goes on and
        # ends as before, with the settings link
        r = self.run_script("push", "t", FAKE_EXIT="1")
        ...
```

The last one is the existing test with `FAKE_EXIT="1"` added (the fake `gh` and the fake `podman` both read `FAKE_EXIT`; make the fake `podman push` exit 0 regardless by giving `FAKE_RUNNER` a `FAKE_EXIT_<PROG>` override, or write the fake `gh` as its own two-line script that exits `${FAKE_GH_EXIT:-0}`; the smaller change wins). Its log becomes `["workflow run seed.yml -R owner/repo -f tool=t", "push ghcr.io/owner/repo/t:src-abc"]` and its exit stays 3. `test_push_does_not_call_a_registry_error_private` stays as it is (a registry error is not "cannot be read": `--published` raises like `--resolve`).

In `tests/test_check.py`, beside the `--resolve` tests: `--published` prints the tags the fake registry serves and exits 4 when the token endpoint refuses.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -I -m unittest tests.test_scripts tests.test_check -v 2>&1 | tail -15`
Expected: the three push tests fail (`gh` never called; `--published` unknown).

- [ ] **Step 3: Implement**

`check.py`: `--published TOOL_DIR` in the mutually exclusive group with `--candidate` and `--resolve`; it calls `_token(host, repo, name)` and exits 4 with `package <name> is not in the registry or not public` when refused, else prints `published_tags(...)` sorted, one per line.

`scripts/push`, before `podman push`:

```bash
path=${image#*/}; owner=${path%%/*}; repo=${path#*/}; repo=${repo%%/*}
if ! python3 -I scripts/check.py --published "tools/$1" > /dev/null 2> "$err"; then
  if grep -q "not in the registry or not public" "$err"; then
    echo "no public package for $1 yet: asking $owner/$repo's seed workflow to create it"
    if gh workflow run seed.yml -R "$owner/$repo" -f "tool=$1"; then
      for _ in $(seq 60); do  # the run queues, starts, and pushes the placeholder: a minute or two
        sleep 5
        python3 -I scripts/check.py --published "tools/$1" 2> /dev/null | grep -qx seed && break
      done
    fi
  else
    cat "$err" >&2; exit 1  # a registry error, not a missing package
  fi
fi
podman push "$image"
```

Then the existing resolve check (exit 0, or 3 with the settings link). Move `err=$(mktemp)` and the `owner`/`repo` derivation above the push so both halves share them. Keep `set -euo pipefail` happy: the `grep -qx seed` in the loop is in a condition.

- [ ] **Step 4: Run the tests**

Run: `python3 -I -m unittest discover tests 2>&1 | tail -3`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/check.py scripts/push tests/test_scripts.py tests/test_check.py
git commit -m "scripts/push asks the seed workflow to create a new tool's package, public and linked, before pushing its candidate"
```

### Task 3: The design and the guidance

**Files:**
- Modify: `docs/DESIGN.md` §2 (the layout block's `scripts/push` line; the registry paragraph; the workflow list; the status line), §7 (the deferred row); `CONTRIBUTING.md` step 4; `README.md` (the last paragraph)

- [ ] **Step 1: Rewrite the registry paragraph**

Replace, in §2's registry paragraph, everything from "GitHub makes a new package private on its first push" to the end of the paragraph with: "GitHub fixes a package's visibility when it is created, from the credential that creates it: a token's push makes a private package, and no API changes that afterwards; a workflow's `GITHUB_TOKEN` in a public repository makes a public package linked to the repository, inheriting its permissions. So **a new tool's package is created by the shed's own workflow**: `seed.yml`, dispatched by `scripts/push` when the registry cannot serve the package anonymously, pushes a one-file placeholder tagged `seed`, and the contributor's push of the real candidate follows with their own credential. Nobody opens a package's settings. The organization's package creation setting allows public packages (it once allowed only private ones)." Keep the sentences about `scripts/build`'s source label (it still links the images themselves) and the licensed-tool exception.

- [ ] **Step 2: The rest**

The layout line: `scripts/push <name>       push the candidate; a new tool's package is first created by seed.yml`. The workflow list gains, before `check`: "`seed`, on dispatch only, with `GITHUB_TOKEN`: the placeholder that creates a tool's package; it checks out nothing and runs no Containerfile." The sentence "It never builds, pulls, or runs an image; it reads the registry." gains "and `seed` pushes a placeholder that is not a tool". §7: delete the row "A shed in its own organization whose package creation is public only...". The status line: "amended <date> so that a new tool's package is created public by the shed's seed workflow (§2), not by hand". `CONTRIBUTING.md` step 4: after the `podman login` sentence, replace the three sentences about the private package with: "Sign in to `gh` too (`gh auth login`): a tool's first push asks the shed's `seed.yml` to create its package, public and linked, and waits for it. Then `scripts/push <name>`. It exits 0 when the candidate can be pulled with no login." `README.md`, last paragraph: "CI never builds or runs an image" becomes "CI never builds or runs a tool image: it checks, promotes, and creates a new tool's package with a placeholder".

- [ ] **Step 3: Commit**

```bash
git add docs/DESIGN.md CONTRIBUTING.md README.md
git commit -m "A new tool's package is created public by the seed workflow, so nobody opens a package's settings"
```

### Task 4 [human]: Verify on the scratch shed, then land

- [ ] **Step 1: The scratch shed first**

Push the branch to `toolshed-dev` (or merge it into its `main`, as before, so the workflow file exists there), then from a laptop with `gh` signed in and `podman login ghcr.io` done:

```bash
gh workflow run seed.yml -R brineylab/toolshed-dev -f tool=seed-probe
gh run watch -R brineylab/toolshed-dev "$(gh run list -R brineylab/toolshed-dev --workflow seed.yml -L1 --json databaseId --jq '.[0].databaseId')"
gh api orgs/brineylab/packages/container/toolshed-dev%2Fseed-probe --jq '{visibility, repository: .repository.full_name}'
skopeo inspect --no-creds docker://ghcr.io/brineylab/toolshed-dev/seed-probe:seed --format '{{.Digest}}'
podman tag ghcr.io/brineylab/toolshed-dev/hello:src-<any local candidate> ghcr.io/brineylab/toolshed-dev/seed-probe:probe
podman push ghcr.io/brineylab/toolshed-dev/seed-probe:probe
```

Expected: visibility `public` and the repository `brineylab/toolshed-dev`; the anonymous inspect answers a digest; the push with your own token succeeds (the inherited write access). Also dispatch with `tool=Seed_Probe` and see the run fail at the name check. Record the three facts in DESIGN's status line. Delete the probe if you like: `gh api -X DELETE orgs/brineylab/packages/container/toolshed-dev%2Fseed-probe` (the token needs `delete:packages`); leaving it is harmless. Do not seed `hello2` by hand: flyloft's tier two builds it through this path.

- [ ] **Step 2: Land**

Open the pull request on `brineylab/toolshed` (its `check` runs nothing for a change outside `tools/`), merge, and merge `main` into `toolshed-dev` as before so the two stay in step. Then flyloft's follow-up removes its `private` state and passes `GH_TOKEN` to its build process.
