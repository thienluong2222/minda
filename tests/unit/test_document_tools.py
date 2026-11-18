"""Document tool discovery must also work outside the Codex shell."""

from meeting_pipeline.minutes import document_tools


def test_standard_install_is_found_without_shell_path(tmp_path, monkeypatch):
    executable = tmp_path / "LibreOffice.app/Contents/MacOS/soffice"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setitem(document_tools.TOOL_LOCATIONS, "soffice", (str(executable),))
    assert document_tools.find_document_tool("soffice") == str(executable)
    executable.chmod(0o644)
    assert document_tools.find_document_tool("soffice") is None


def test_libreoffice_alias_is_reported_as_preview_capability(tmp_path, monkeypatch):
    for name in ["libreoffice", "pdftoppm"]:
        path = tmp_path / name
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert document_tools.preview_tools() == {
        "libreoffice": str(tmp_path / "libreoffice"),
        "pdftoppm": str(tmp_path / "pdftoppm"),
    }


def test_missing_preview_dependencies_are_not_reported_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(document_tools, "TOOL_LOCATIONS", {"soffice": (), "pdftoppm": ()})
    assert not all(document_tools.preview_tools().values())
