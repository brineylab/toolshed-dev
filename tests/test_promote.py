import unittest, tempfile, subprocess, os
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "promote"

# A stand-in for skopeo: inspect prints the digest stored in $FAKE_DIR/<tag>, or fails like GHCR.
FAKE = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
ref="${@: -1}"; tag="${ref##*:}"
if [[ "$1" == inspect ]]; then
  [[ -f "$FAKE_DIR/$tag" ]] || { echo "reading manifest $tag: manifest unknown" >&2; exit 2; }
  d=$(cat "$FAKE_DIR/$tag")
  [[ "$d" == error ]] && { echo "received unexpected HTTP status: 500 Internal Server Error" >&2; exit 2; }
  echo "$d"
fi
"""

class PromoteTests(unittest.TestCase):
    def promote(self, tags, tested="sha256:a"):
        d = Path(tempfile.mkdtemp())
        (d / "bin").mkdir(); (d / "tags").mkdir()
        (d / "bin" / "skopeo").write_text(FAKE); (d / "bin" / "skopeo").chmod(0o755)
        for tag, digest in tags.items():
            (d / "tags" / tag).write_text(digest)
        env = {**os.environ, "PATH": f"{d / 'bin'}:{os.environ['PATH']}", "FAKE_DIR": str(d / "tags"), "FAKE_LOG": str(d / "log")}
        r = subprocess.run(["bash", str(SCRIPT), "ghcr.io/o/r/t", "pr-1-abc", tested, "1.0.0"], env=env, capture_output=True, text=True)
        log = (d / "log").read_text() if (d / "log").exists() else ""
        copies = [l for l in log.splitlines() if l.startswith("copy")]
        return r.returncode, copies, r.stdout + r.stderr

    def test_an_unpublished_version_is_copied_from_the_candidate_with_its_digest(self):
        code, copies, _ = self.promote({"pr-1-abc": "sha256:a"})
        self.assertEqual(code, 0)
        self.assertEqual(copies, ["copy --preserve-digests docker://ghcr.io/o/r/t@sha256:a docker://ghcr.io/o/r/t:1.0.0"])
    def test_a_candidate_rebuilt_after_its_test_is_refused(self):
        code, copies, out = self.promote({"pr-1-abc": "sha256:b"}, tested="sha256:a")
        self.assertEqual((code, copies), (1, []))
        self.assertIn("the record tested sha256:a", out)
    def test_a_version_already_promoted_from_this_candidate_passes_without_copying(self):
        code, copies, out = self.promote({"pr-1-abc": "sha256:a", "1.0.0": "sha256:a"})
        self.assertEqual((code, copies), (0, []))
        self.assertIn("already promoted", out)
    def test_a_version_published_as_another_image_is_refused(self):
        code, copies, out = self.promote({"pr-1-abc": "sha256:a", "1.0.0": "sha256:b"})
        self.assertEqual((code, copies), (1, []))
        self.assertIn("already published", out)
    def test_a_registry_error_is_not_taken_for_an_unpublished_version(self):
        code, copies, _ = self.promote({"pr-1-abc": "sha256:a", "1.0.0": "error"})
        self.assertEqual((code, copies), (1, []))
    def test_a_candidate_this_registry_never_saw_is_skipped(self):
        # a tool merged in from another shed (the scratch shed's syncs): its candidate lives in that shed's registry
        code, copies, out = self.promote({})
        self.assertEqual((code, copies), (0, []))
        self.assertIn("not in this registry", out)
        self.assertIn("skipped", out)
    def test_a_registry_error_on_the_candidate_is_not_taken_for_a_missing_one(self):
        code, copies, _ = self.promote({"pr-1-abc": "error"})
        self.assertEqual((code, copies), (1, []))
    def test_a_promotion_says_what_it_published(self):
        code, _, out = self.promote({"pr-1-abc": "sha256:a"})
        self.assertEqual(code, 0)
        self.assertIn("published ghcr.io/o/r/t:1.0.0 from pr-1-abc", out)

if __name__ == "__main__":
    unittest.main()
