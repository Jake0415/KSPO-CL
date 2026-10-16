"""Data Quality Report — 사이트별/전체 품질 리포트 생성."""
from __future__ import annotations

from dataclasses import dataclass, field

from kspo_ingest.quality.checks import CheckStatus, DocumentCheckReport


@dataclass
class SiteReport:
    """사이트 단위 품질 집계."""
    host: str
    total_docs: int = 0
    pass_count: int = 0
    warning_count: int = 0
    fail_count: int = 0
    avg_score: float = 0.0
    check_scores: dict[str, float] = field(default_factory=dict)  # check_name → avg score
    common_issues: list[str] = field(default_factory=list)
    remedies: list[str] = field(default_factory=list)
    # 재처리 대상
    recrawl_urls: list[str] = field(default_factory=list)
    reparse_urls: list[str] = field(default_factory=list)
    reembed_urls: list[str] = field(default_factory=list)
    delete_urls: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_docs == 0:
            return 0.0
        return self.pass_count / self.total_docs


def aggregate_site_report(host: str, doc_reports: list[DocumentCheckReport]) -> SiteReport:
    """문서별 결과를 사이트 단위로 집계."""
    site = SiteReport(host=host, total_docs=len(doc_reports))
    if not doc_reports:
        return site

    # 상태 집계
    all_scores: list[float] = []
    check_totals: dict[str, list[float]] = {}
    issue_counts: dict[str, int] = {}

    for doc in doc_reports:
        all_scores.append(doc.overall_score)

        if doc.overall_status == CheckStatus.PASS:
            site.pass_count += 1
        elif doc.overall_status == CheckStatus.WARNING:
            site.warning_count += 1
        else:
            site.fail_count += 1

        for check in doc.checks:
            check_totals.setdefault(check.name, []).append(check.score)
            if check.status != CheckStatus.PASS:
                issue_counts[check.detail[:80]] = issue_counts.get(check.detail[:80], 0) + 1

        # 재처리 분류
        if doc.overall_status == CheckStatus.FAIL:
            fail_checks = [c.name for c in doc.checks if c.status == CheckStatus.FAIL]
            if "body_length" in fail_checks or "broken_chars" in fail_checks:
                site.recrawl_urls.append(doc.url)
            elif "boilerplate_removal" in fail_checks:
                site.reparse_urls.append(doc.url)
            elif doc.overall_score < 0.3:
                site.delete_urls.append(doc.url)

    site.avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
    site.check_scores = {
        name: sum(scores) / len(scores) for name, scores in check_totals.items()
    }

    # 빈도순 이슈
    site.common_issues = sorted(issue_counts, key=issue_counts.get, reverse=True)[:10]

    # 유니크 remedy 수집
    seen_remedies: set[str] = set()
    for doc in doc_reports:
        for r in doc.remedies:
            if r not in seen_remedies:
                seen_remedies.add(r)
                site.remedies.append(r)

    return site


def format_report_text(site: SiteReport) -> str:
    """사이트 리포트를 텍스트로 포맷."""
    lines: list[str] = []
    lines.append(f"{'='*70}")
    lines.append(f"  Site: {site.host}")
    lines.append(f"{'='*70}")
    lines.append(f"  Documents  : {site.total_docs}")
    lines.append(f"  PASS       : {site.pass_count} ({site.success_rate:.0%})")
    lines.append(f"  WARNING    : {site.warning_count}")
    lines.append(f"  FAIL       : {site.fail_count}")
    lines.append(f"  Avg Score  : {site.avg_score:.3f}")
    lines.append("")

    if site.check_scores:
        lines.append("  Check Scores:")
        for name, score in sorted(site.check_scores.items()):
            bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
            lines.append(f"    {name:<25} {bar} {score:.3f}")
        lines.append("")

    if site.common_issues:
        lines.append("  Common Issues:")
        for issue in site.common_issues[:5]:
            lines.append(f"    - {issue}")
        lines.append("")

    if site.remedies:
        lines.append("  Remedies:")
        for r in site.remedies[:5]:
            lines.append(f"    - {r}")
        lines.append("")

    if site.recrawl_urls:
        lines.append(f"  Re-crawl ({len(site.recrawl_urls)}):")
        for u in site.recrawl_urls[:3]:
            lines.append(f"    {u}")
        lines.append("")

    if site.reparse_urls:
        lines.append(f"  Re-parse ({len(site.reparse_urls)}):")
        for u in site.reparse_urls[:3]:
            lines.append(f"    {u}")

    if site.delete_urls:
        lines.append(f"  Delete ({len(site.delete_urls)}):")
        for u in site.delete_urls[:3]:
            lines.append(f"    {u}")

    return "\n".join(lines)


def format_doc_report_text(doc: DocumentCheckReport) -> str:
    """문서 1건 리포트 텍스트."""
    status_icons = {
        CheckStatus.PASS: "✅",
        CheckStatus.WARNING: "⚠️",
        CheckStatus.FAIL: "❌",
    }
    lines: list[str] = []
    icon = status_icons[doc.overall_status]
    lines.append(f"{icon} [{doc.overall_score:.2f}] {doc.url}")
    for c in doc.checks:
        ci = status_icons[c.status]
        lines.append(f"  {ci} {c.name:<25} {c.score:.2f}  {c.detail[:60]}")
        if c.remedy:
            lines.append(f"     → {c.remedy[:70]}")
    return "\n".join(lines)
