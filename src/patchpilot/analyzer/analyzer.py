"""Repository analysis: scan, parse, and run the profile's detector."""

from __future__ import annotations

from pathlib import Path

from patchpilot.analyzer.parser import ParsedFile, parse
from patchpilot.analyzer.scanner import scan
from patchpilot.models import AnalysisReport, FileInfo
from patchpilot.profiles.base import Profile


def analyze(root: Path, profile: Profile) -> AnalysisReport:
    root = root.resolve()
    sources, skipped = scan(root)
    parsed: list[ParsedFile] = []
    infos: list[FileInfo] = []
    for src in sources:
        data = src.abspath.read_bytes()
        tree = parse(data)
        parsed.append(ParsedFile(src.path, data, tree.root_node, src.is_test))
        infos.append(
            FileInfo(
                path=src.path,
                lines=data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0),
                is_test=src.is_test,
                parse_error=tree.root_node.has_error,
            )
        )
    findings, models = profile.detect(parsed)
    # Test files are context for model discovery, but never migration targets.
    test_files = {p.path for p in parsed if p.is_test}
    findings = [f for f in findings if f.file not in test_files]
    return AnalysisReport(
        root=str(root), files=infos, findings=findings, model_classes=models, skipped=skipped
    )
