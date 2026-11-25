"""Arranque automático: la orden registrada y cuándo cerrar el coach (sin tocar el registro)."""
from coach.autostart import DotaWatcher, command


def test_command_frozen_and_source(tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_text("")
    assert command(frozen=True, executable=str(tmp_path / "DotaCoach.exe")).endswith('DotaCoach.exe" autostart')
    src = command(frozen=False, executable=str(exe))
    assert src.startswith(f'"{exe}"') and src.endswith('run.py" autostart')
    (tmp_path / "pythonw.exe").write_text("")
    assert "pythonw.exe" in command(frozen=False, executable=str(exe))   # sin consola si existe pythonw


def test_watcher_needs_two_misses():
    states = iter([True, False, False])
    w = DotaWatcher(running=lambda: next(states), every=0)
    assert [w.should_stop(), w.should_stop(), w.should_stop()] == [False, False, True]
