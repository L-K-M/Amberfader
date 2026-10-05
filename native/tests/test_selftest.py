"""Renderer sandbox detection for --self-test, on synthetic /proc trees
shaped like Qt WebEngine 6.11's processes with and without the sandbox."""
import pytest

pytest.importorskip(
    "PySide6.QtWebEngineCore", reason="Qt WebEngine unavailable", exc_type=ImportError,
)

from amberfader.embedded.selftest import renderer_sandbox

ENGINE = "/opt/amberfader/lib/PySide6/Qt/libexec/QtWebEngineProcess"
ZYGOTE = [ENGINE, "--type=zygote", "--application-name=amberfader"]
UNSANDBOXED_ZYGOTE = [ENGINE, "--type=zygote", "--no-zygote-sandbox"]
BROWSER = 100


def make_proc(tmp_path, processes):
    """processes: {pid: (ppid, argv, seccomp)}"""
    for pid, (ppid, argv, seccomp) in processes.items():
        entry = tmp_path / str(pid)
        entry.mkdir()
        (entry / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
        (entry / "status").write_text(f"Name:\tx\nPPid:\t{ppid}\nSeccomp:\t{seccomp}\n")
    (tmp_path / "self").mkdir()
    return tmp_path


def sandboxed(renderer_seccomp=(2, 2)):
    tree = {
        BROWSER: (1, ["python3", "-m", "amberfader"], 0),
        101: (BROWSER, UNSANDBOXED_ZYGOTE, 0),
        102: (101, UNSANDBOXED_ZYGOTE, 0),            # unsandboxed utility: ignored
        103: (BROWSER, ZYGOTE, 0),                    # init of the sandbox namespace
        104: (103, ZYGOTE, 0),                        # the zygote itself
    }
    for offset, seccomp in enumerate(renderer_seccomp):
        tree[110 + offset] = (104, ZYGOTE, seccomp)  # renderers
    return tree


def test_sandboxed_renderers_are_on(tmp_path):
    assert renderer_sandbox(make_proc(tmp_path, sandboxed()), BROWSER) == "on"


def test_one_unfiltered_renderer_is_off(tmp_path):
    assert renderer_sandbox(make_proc(tmp_path, sandboxed((2, 0))), BROWSER) == "off"


def test_disabled_sandbox_is_off(tmp_path):
    tree = {
        BROWSER: (1, ["python3"], 0),
        201: (BROWSER, [ENGINE, "--type=zygote", "--no-sandbox"], 0),
        202: (201, [ENGINE, "--type=zygote", "--no-sandbox"], 0),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "off"


def test_only_unsandboxed_helpers_is_absent(tmp_path):
    tree = {
        BROWSER: (1, ["python3"], 0),
        101: (BROWSER, UNSANDBOXED_ZYGOTE, 0),
        102: (101, UNSANDBOXED_ZYGOTE, 0),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "absent"


def test_other_processes_renderers_are_ignored(tmp_path):
    tree = sandboxed()
    tree[300] = (1, ["python3"], 0)
    assert renderer_sandbox(make_proc(tmp_path, tree), 300) == "absent"


def test_renderer_started_without_a_zygote_counts(tmp_path):
    tree = {
        BROWSER: (1, ["python3"], 0),
        120: (BROWSER, [ENGINE, "--type=renderer"], 2),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "on"
