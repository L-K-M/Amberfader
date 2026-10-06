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
    """processes: {pid: (ppid, argv, seccomp)} or
    {pid: (ppid, argv, seccomp, seccomp_filters, nspid)}; the short form
    means no filters and no nested PID namespace."""
    for pid, (ppid, argv, seccomp, *kernel) in processes.items():
        filters, nspid = kernel or (1 if seccomp == 2 else 0, str(pid))
        entry = tmp_path / str(pid)
        entry.mkdir()
        (entry / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
        status = f"Name:\tx\nPPid:\t{ppid}\nNSpid:\t{nspid}\nSeccomp:\t{seccomp}\n"
        if filters is not None:
            status += f"Seccomp_filters:\t{filters}\n"
        (entry / "status").write_text(status)
    (tmp_path / "self").mkdir()
    return tmp_path


def sandboxed(renderer_seccomp=(2, 2)):
    """Shaped like the namespace sandbox: the zygote's init process is PID 1
    of a new PID namespace, and renderers add their own seccomp filter."""
    tree = {
        BROWSER: (1, ["python3", "-m", "amberfader"], 0),
        101: (BROWSER, UNSANDBOXED_ZYGOTE, 0),
        102: (101, UNSANDBOXED_ZYGOTE, 0),            # unsandboxed utility: ignored
        103: (BROWSER, ZYGOTE, 0, 0, "103\t1"),       # init of the sandbox namespace
        104: (103, ZYGOTE, 0, 0, "104\t2"),           # the zygote itself
    }
    for offset, seccomp in enumerate(renderer_seccomp):
        pid = 110 + offset
        tree[pid] = (104, ZYGOTE, seccomp, int(seccomp == 2), f"{pid}\t{3 + offset}")
    return tree


def confined(tree, filters=1):
    """The same tree started under an inherited seccomp filter, as in a
    Docker container or a Flatpak: every process carries it."""
    out = {}
    for pid, (ppid, argv, _seccomp, *kernel) in tree.items():
        own, nspid = kernel or (0, str(pid))
        out[pid] = (ppid, argv, 2, own + filters, nspid)
    return out


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
        120: (BROWSER, [ENGINE, "--type=renderer"], 2, 1, "120\t1"),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "on"


def test_inherited_seccomp_filter_is_not_the_sandbox(tmp_path):
    """Observed in Docker with QTWEBENGINE_DISABLE_SANDBOX=1: every process,
    the browser included, shows Seccomp: 2 from the container's filter."""
    tree = {
        BROWSER: (1, ["python3"], 2, 1, str(BROWSER)),
        201: (BROWSER, [ENGINE, "--type=zygote", "--no-sandbox"], 2, 1, "201"),
        202: (201, [ENGINE, "--type=zygote", "--no-sandbox"], 2, 1, "202"),
    }
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "off"


def test_sandbox_under_an_inherited_filter_is_on(tmp_path):
    proc = make_proc(tmp_path, confined(sandboxed()))
    assert renderer_sandbox(proc, BROWSER) == "on"


def test_renderer_without_its_own_filter_is_off_under_an_inherited_one(tmp_path):
    tree = confined(sandboxed())
    ppid, argv, seccomp, _filters, nspid = tree[111]
    tree[111] = (ppid, argv, seccomp, 1, nspid)
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "off"


def test_renderer_in_the_browsers_pid_namespace_is_off(tmp_path):
    """Seccomp alone is not the sandbox: renderers must also sit in the new
    PID namespace that Chromium's namespace sandbox creates."""
    tree = sandboxed()
    for pid in (103, 104, 110, 111):
        ppid, argv, seccomp, filters, _nspid = tree[pid]
        tree[pid] = (ppid, argv, seccomp, filters, str(pid))
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "off"


def test_no_sandbox_flag_is_off_whatever_the_kernel_shows(tmp_path):
    tree = sandboxed()
    for pid in (110, 111):
        ppid, argv, seccomp, filters, nspid = tree[pid]
        tree[pid] = (ppid, [*argv, "--no-sandbox"], seccomp, filters, nspid)
    assert renderer_sandbox(make_proc(tmp_path, tree), BROWSER) == "off"


def without_filter_counts(tree):
    """Kernels before 5.9 have no Seccomp_filters line."""
    return {
        pid: (ppid, argv, seccomp, None, kernel[1] if kernel else str(pid))
        for pid, (ppid, argv, seccomp, *kernel) in tree.items()
    }


def test_kernel_without_filter_counts_trusts_an_unconfined_browser(tmp_path):
    proc = make_proc(tmp_path, without_filter_counts(sandboxed()))
    assert renderer_sandbox(proc, BROWSER) == "on"


def test_kernel_without_filter_counts_cannot_judge_a_confined_browser(tmp_path):
    proc = make_proc(tmp_path, without_filter_counts(confined(sandboxed())))
    assert renderer_sandbox(proc, BROWSER) == "unknown"


def test_self_test_never_uses_a_given_socket(tmp_path):
    """--self-test with --socket must not reach (and raise) a running
    instance's socket; it always uses its own scratch socket."""
    import argparse

    from amberfader.embedded.__main__ import _socket_path

    args = argparse.Namespace(self_test=True, socket="/run/live.sock")
    assert _socket_path(args, str(tmp_path)) == str(tmp_path / "self-test.sock")
    with pytest.raises(RuntimeError):
        _socket_path(argparse.Namespace(self_test=True, socket=None), None)
    args = argparse.Namespace(self_test=False, socket="/run/live.sock")
    assert _socket_path(args, str(tmp_path)) == "/run/live.sock"


def test_unexpected_error_still_prints_the_verdict(monkeypatch):
    from types import SimpleNamespace

    from amberfader.embedded import selftest

    def broken_checks(self):
        raise KeyError("results")

    monkeypatch.setattr(selftest.SelfTest, "_checks", broken_checks)
    runtime = SimpleNamespace(
        upstream=SimpleNamespace(messageReceived=SimpleNamespace(connect=lambda _f: None)),
        amber=SimpleNamespace(window=SimpleNamespace(route_response=lambda *_a: None)),
    )
    lines: list[str] = []
    assert selftest.SelfTest(runtime, out=lines.append).run() == 1
    assert lines[-1] == selftest.FAILED
    assert any("unexpected error" in line and "KeyError" in line for line in lines)
