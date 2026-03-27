from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

import httpx
from rich.console import Console

console = Console()


class Notifier:
    def __init__(
        self,
        slack_webhook: str | None = None,
        email_config: dict | None = None,
    ):
        self.slack_webhook = slack_webhook
        self.email_config = email_config

    def notify(
        self,
        dashboard_title: str,
        dashboard_url: str,
        chart_count: int,
        issues: list[str],
    ) -> None:
        try:
            if self.slack_webhook:
                self._send_slack(dashboard_title, dashboard_url, chart_count, issues)
            if self.email_config:
                self._send_email(dashboard_title, dashboard_url, chart_count, issues)
        except Exception as exc:
            console.print(f"[yellow]Warning: notification failed: {exc}[/yellow]")

    def _send_slack(
        self,
        title: str,
        url: str,
        chart_count: int,
        issues: list[str],
    ) -> None:
        issue_text = f"\n{len(issues)} issue(s) found" if issues else "\nAll QA checks passed"
        payload = {
            "text": f"Dashboard ready: {title}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*{title}* is ready\n"
                            f"{chart_count} charts\n"
                            f"<{url}|Open dashboard>"
                            f"{issue_text}"
                        ),
                    },
                }
            ],
        }
        with httpx.Client(timeout=10) as client:
            resp = client.post(self.slack_webhook, json=payload)
            if resp.status_code != 200:
                console.print(
                    f"[yellow]Slack notification returned {resp.status_code}: {resp.text}[/yellow]"
                )

    def _send_email(
        self,
        title: str,
        url: str,
        chart_count: int,
        issues: list[str],
    ) -> None:
        cfg = self.email_config
        issue_lines = "\n".join(f"  - {i}" for i in issues) if issues else "  None"
        body = (
            f"Dashboard '{title}' has been created/updated.\n\n"
            f"URL: {url}\n"
            f"Charts: {chart_count}\n\n"
            f"QA Issues:\n{issue_lines}"
        )
        msg = MIMEText(body)
        msg["Subject"] = f"[Superset] Dashboard ready: {title}"
        msg["From"] = cfg.get("from_addr", "")
        msg["To"] = cfg.get("to_addr", "")

        with smtplib.SMTP(cfg.get("smtp_host", "smtp.gmail.com"), cfg.get("smtp_port", 587)) as server:
            server.starttls()
            server.login(cfg.get("from_addr", ""), cfg.get("password", ""))
            server.sendmail(cfg.get("from_addr", ""), cfg.get("to_addr", ""), msg.as_string())
