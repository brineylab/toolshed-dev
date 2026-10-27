# Toolshed, Plan A3: A Tool Never Carries a Credential Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nothing that goes public through the shed holds a credential: `check.py` scans a tool's directory and a test's record for the shapes of tokens, keys, and credential files, and for `ARG`/`ENV` lines that would bake one into an image; `scripts/build` refuses before anything is built or pushed, `scripts/record` refuses before a record is written, and `check` refuses the pull request as the backstop. Every refusal names the file, the line, what it looks like, and the fix.

**Architecture:** A candidate image is public the moment `scripts/push` pushes it, and a record is public at the merge, so the scan runs where each is made, not only in CI. One rule in one owner: `check.py` gains `secrets_in(paths)` (stdlib `re`, no new binary on laptops, hosted runners, or the flyloft host), used by `check_tool` for `tools/<name>/`, by `check_candidate` for the record, and by a `--scan FILE...` mode that `scripts/record` calls. The sanctioned path for a gated-weights token, `--mount=type=secret`, is untouched and passes.

**Tech Stack:** Python 3 stdlib (`re`, `pathlib`), bash, `unittest`.

**Spec:** `docs/DESIGN.md` §2 (the guards paragraph) and §7, as Task 3 amends them; `CONTRIBUTING.md`'s conventions.

## Global Constraints

- The rule lives in `scripts/check.py` and nowhere else; `scripts/build`, `scripts/record`, and `check` call it. Python 3.8 or later, stdlib only, as the rest of `check.py`.
- A reason reads `tools/<name>: <path under the tool's directory>:<line> holds what looks like <what>; a tool never carries a credential: pass it as the build secret (CONTRIBUTING, "Weights behind a login")`; for an `ARG`/`ENV`, `tools/<name>: Containerfile:<line> declares <ARG|ENV> <NAME>: an ARG stays in the image's history and an ENV in the image; pass a credential as the build secret (CONTRIBUTING, "Weights behind a login")`; for a file named like a credential, `tools/<name>: <path> is a credential file by name; a tool never carries one`; for a record, `<record path>:<line> holds what looks like <what>; the test's output must not print a credential or the job's environment`.
- What is scanned: every file under `tools/<name>/` except those whose first 8 KiB hold a NUL byte (binary fixtures), read as UTF-8 with replacement; and the record's body.
- The shapes (name, regex), applied per line:
  - a GitHub token: `\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{80,})`
  - a Hugging Face token: `\bhf_[A-Za-z0-9]{30,}`
  - an AWS access key: `\b(AKIA|ASIA)[0-9A-Z]{16}\b`
  - an OpenAI or Anthropic key: `\bsk-(ant-)?[A-Za-z0-9_-]{20,}`
  - a Slack token: `\bxox[abprs]-[A-Za-z0-9-]{10,}`
  - a private key: `-----BEGIN [A-Z ]*PRIVATE KEY-----`
  - a password or token assignment: `(?i)\b(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*['"]?[A-Za-z0-9/+_\-]{16,}` (a value that starts with `$`, such as `$(cat /run/secrets/hf_token)`, does not match)
- In a Containerfile, a line matching `^\s*(ARG|ENV)\s+([A-Z0-9_]*(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_KEY|ACCESS_KEY|PRIVATE_KEY)[A-Z0-9_]*)` is refused by name, whatever its value.
- Credential files by name, anywhere under the tool: `.netrc`, `.env` and `.env.*`, `.npmrc`, `.pypirc`, `id_rsa`, `id_ed25519`, `id_ecdsa`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `credentials.json`, `kaggle.json`, `token.txt`, `config.json` under a `.docker` directory.
- `check.py --scan FILE...` prints each hit to stderr and exits 1 on any hit, 0 otherwise; `scripts/record` runs it on the record it wrote and, on a hit, removes the record and exits 1. `scripts/build` runs `python3 -I scripts/check.py "tools/$1"` (the directory's rules, no registry) after its uncommitted-changes check and before `podman build`, and exits 1 with the reasons when it fails.
- Tests: `python3 -I -m unittest discover tests` stays green; the fake `check.py` in `tests/test_scripts.py` delegates a plain directory argument and `--scan` to the real module's `main`, so `build` and `record` are tested against the real rule.
- Commit message style as the repository's: one sentence stating the behavior.

## Review Focus

1. **The sanctioned secret mount:** `RUN --mount=type=secret,id=hf_token HF_TOKEN=$(cat /run/secrets/hf_token) ...` passes every rule. Test in Task 1.
2. **Prose that uses the words:** a skill that says "the token stays with whoever builds" or "password: see the README" passes; only a long credential-shaped value after `=` or `:` is a hit. Test in Task 1.
3. **A binary fixture** (`.npz`, `.pt`) with token-shaped bytes inside is skipped, not refused. Test in Task 1.
4. **A record whose test printed the job's environment** with a token in it is refused before it is written, and the refusal says what to change. Test in Task 2.
5. **A credential a `RUN` step downloads and writes into a layer** is not seen by any of this; the design says so and defers scanning layers.

---

### Task 1: `check.py` refuses a credential in a tool's directory or a record

**Files:**
- Modify: `scripts/check.py`
- Test: `tests/test_check.py`

**Interfaces:**
- Produces: `secrets_in(paths: list[Path], root: Path) -> list[tuple[str, int, str]]` (relative path, line number, what it looks like; a credential file by name has line 0 and the what `a credential file by name`); `check_tool` and `check_candidate` fold its hits into their reasons in the constraints' wording; `--scan FILE...` on the command line.

- [ ] **Step 1: Write the failing tests**

In `tests/test_check.py`, using the module's `tool(...)` helper:

```python
    def test_a_tool_holding_a_credential_is_refused_with_the_file_and_line(self):
        cases = [  # (what to write, where, the words the reason must hold)
            ("export HF_TOKEN=hf_" + "a" * 34 + "\n", "bin/x", ("bin/x:1", "Hugging Face token", "build secret")),
            ("FROM x\nARG HF_TOKEN\nCOPY test /toolshed/test\n", "Containerfile", ("Containerfile:2", "ARG HF_TOKEN", "history")),
            ("FROM x\nENV GITHUB_TOKEN=abc\nCOPY test /toolshed/test\n", "Containerfile", ("Containerfile:2", "ENV GITHUB_TOKEN",)),
            ("-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n", "test/fixture.txt", ("test/fixture.txt:1", "private key")),
            ('password = "' + "p" * 20 + '"\n', "bin/x", ("bin/x:1", "password or token")),
            ("machine api.example login me password x\n", "test/.netrc", ("test/.netrc", "credential file by name")),
            ("AKIAIOSFODNN7EXAMPLE\n", "test/run.sh", ("test/run.sh:1", "AWS")),
        ]
        for text, where, words in cases:
            root = Path(tempfile.mkdtemp())
            d = tool(root)
            (d / where).parent.mkdir(parents=True, exist_ok=True)
            (d / where).write_text(text)
            reasons = check.check_tool(d, published=set())
            self.assertTrue(any(all(w in r for w in words) for r in reasons), (where, reasons))

    def test_the_secret_mount_prose_and_binary_fixtures_pass(self):
        d = tool(self.root, containerfile=(
            "FROM x\nRUN --mount=type=secret,id=hf_token HF_TOKEN=$(cat /run/secrets/hf_token) HF_HUB_OFFLINE=0 python -c 'x'\n"
            "ENV HF_HUB_OFFLINE=1\nCOPY test /toolshed/test\n"))
        (d / "SKILL.md").write_text(SKILL.format(name="esm2-650m", version="1.0.0") + "The token stays with whoever builds. password: see the README.\n")
        (d / "test" / "weights.npz").write_bytes(b"\x00PK" + b"hf_" + b"a" * 40)
        self.assertEqual(check.check_tool(d, published=set()), [])

    def test_a_record_holding_a_credential_is_refused(self):
        # check_candidate: the CI backstop
        ... build a tool and a record whose body holds "GITHUB_TOKEN=ghp_" + "x" * 36, the digest and exit matching
            a candidate, and assert a reason holding "results/esm2-650m/1.0.0.txt:" and "job's environment"

    def test_scan_prints_hits_to_stderr_and_exits_1(self):
        p = self.root / "r.txt"; p.write_text("ok\nhf_" + "b" * 34 + "\n")
        with redirect stderr: code = check.main() with sys.argv = ["check.py", "--scan", str(p)]
        self.assertEqual(code, 1); self.assertIn("r.txt:2 holds what looks like a Hugging Face token", err)
        p.write_text("ok\n"); self.assertEqual(main with --scan, 0)
```

Follow the module's existing style for `main()` tests (see `test_published_exits_...`), which set `sys.argv` and capture output.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -I -m unittest tests.test_check -v 2>&1 | tail -12`
Expected: the four new tests fail (`secrets_in` missing; no reasons; `--scan` unknown).

- [ ] **Step 3: Implement**

`SECRETS`, `ENV_ARG`, and `CREDENTIAL_FILES` as module constants in `check.py` (the constraints' regexes and names); `secrets_in(paths, root)` walks the given files, skips binaries, matches per line, and reports credential files by name; `check_tool` calls it over `sorted(tool_dir.rglob("*"))` (files only) and the Containerfile rule; `check_candidate` calls it over the record and words the reason for a record; `main` gains `--scan` (nargs `+`, outside the mutually exclusive group), printing `<path>:<line> holds what looks like <what>` to stderr. The regexes are compiled once.

- [ ] **Step 4: Run the tests**

Run: `python3 -I -m unittest tests.test_check 2>&1 | tail -3`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/check.py tests/test_check.py
git commit -m "check refuses a tool directory or a record that holds what looks like a credential, naming the file and the line"
```

### Task 2: `scripts/build` and `scripts/record` refuse before anything goes public

**Files:**
- Modify: `scripts/build`, `scripts/record`
- Test: `tests/test_scripts.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_scripts.py`'s `FAKE_CHECK`, before the `--candidate` branch: `if "--scan" in sys.argv or not sys.argv[1].startswith("--"): sys.exit(real.main())`, so the rules and the scan are the real ones. Then:

```python
    def test_build_refuses_a_tool_holding_a_credential_before_building(self):
        (self.repo / "tools/t/bin").mkdir()
        (self.repo / "tools/t/bin/x").write_text("export HF_TOKEN=hf_" + "a" * 34 + "\n")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "leak")
        r = self.run_script("build", "t")
        self.assertEqual(r.returncode, 1)
        self.assertIn("tools/t: bin/x:1 holds what looks like a Hugging Face token", r.stdout + r.stderr)
        self.assertEqual(self.log(), [])  # podman never ran
    def test_record_refuses_output_holding_a_credential_and_writes_nothing(self):
        out = "node: n\nGITHUB_TOKEN=ghp_" + "x" * 36 + "\nos=debian\n"
        r = self.run_script("record", "t", "ghcr.io/owner/repo/t@sha256:d", "0", "podman", "h", "2026-01-01T00:00:00Z", input=out)
        self.assertEqual(r.returncode, 1)
        self.assertIn("results/t/1.0.0.txt:", r.stderr); self.assertIn("job's environment", r.stderr)
        self.assertFalse((self.repo / "results/t/1.0.0.txt").exists())
```

(`run_script` may need an `input=` passthrough; the existing record tests show how stdin is given.)

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -I -m unittest tests.test_scripts -v 2>&1 | tail -8`
Expected: both fail (`build` builds; `record` writes the record and exits 0).

- [ ] **Step 3: Implement**

`scripts/build`, after the uncommitted-changes check: `python3 -I scripts/check.py "tools/$1" || exit 1` (the reasons are on its stdout). `scripts/record`, after writing the file: `if ! python3 -I scripts/check.py --scan "results/$name/$version.txt"; then rm -f "results/$name/$version.txt"; exit 1; fi`; the scan's wording for a record comes from `check.py` (it knows a path under `results/` is a record).

- [ ] **Step 4: Run the tests**

Run: `python3 -I -m unittest discover tests 2>&1 | tail -3`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/build scripts/record tests/test_scripts.py
git commit -m "build refuses a tool that holds a credential before anything is built, and record refuses a test's output that holds one before anything is written"
```

### Task 3: The design and the guidance

**Files:**
- Modify: `docs/DESIGN.md` (the status line; §2's guards paragraph; §7), `CONTRIBUTING.md` (the conventions list; "Weights behind a login")

- [ ] **Step 1: The guards paragraph**

Append to §2's **Guards** paragraph: "Nothing that goes public holds a credential: `check.py` scans a tool's directory and a test's record for the shapes of tokens, keys, and credential files, and refuses an `ARG` or `ENV` that would bake one into an image; `scripts/build` refuses before anything is built or pushed, `scripts/record` before a record is written, and `check` refuses the pull request as the backstop, each naming the file, the line, and the fix. What it cannot see is a credential a `RUN` step fetches and writes into a layer; scanning layers is deferred (§7)." The status line gains "amended <date> so that a credential in a tool or a record is refused before it goes public (§2)". §7 gains the row "Scanning an image's layers for a credential a build step wrote (a `RUN` that fetches one) | When a build is seen to do it".

- [ ] **Step 2: The conventions**

`CONTRIBUTING.md`'s conventions list gains, after "Weights are fetched at build time": "**A tool never carries a credential**: not in a file, not as an `ARG` or `ENV`. `scripts/build` refuses one it sees and says where. Gated weights take the build secret (below), which never reaches the image." Under "Weights behind a login", add one sentence: "`scripts/build` refuses a Containerfile that declares `ARG HF_TOKEN` or `ENV HF_TOKEN`, since either would keep the token in the image; the mount is the only way."

- [ ] **Step 3: Run everything and commit**

Run: `python3 -I -m unittest discover tests 2>&1 | tail -3` and, by hand, `python3 -I scripts/check.py tools/hello tools/esm2-650m tools/esmc-600m` (the shed's own tools pass).
Expected: OK; no output and exit 0 from the by-hand check.

```bash
git add docs/DESIGN.md CONTRIBUTING.md
git commit -m "A tool never carries a credential: the guard, where it runs, and what it cannot see"
```

### Task 4 [human]: Land, and keep the scratch shed in step

Open the pull request on `brineylab/toolshed` (`check` runs nothing for a change outside `tools/`), merge, and merge `main` into `toolshed-dev` as before.

**flyloft's follow-up (its task 17, after this lands):** `_record` treats a failing `scripts/record` as a failed build (a `tool_result` `failed` with the script's stderr), rather than retrying each tick; the implementer's toolshed prose gains the sentence that a tool never carries a credential and gated weights take the build secret. `scripts/build`'s refusal already reaches the implementer unchanged, as the failed build's log tail.
