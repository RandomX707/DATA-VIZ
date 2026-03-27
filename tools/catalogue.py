from __future__ import annotations

import json
import os

from models.schemas import CatalogueEntry

CATALOGUE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "charts_catalogue.json")


class CatalogueManager:
    def __init__(self, path: str = CATALOGUE_PATH):
        self.path = path

    def load(self) -> list[CatalogueEntry]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path) as f:
                content = f.read().strip()
                if not content:
                    return []
                raw = json.loads(content)
                return [CatalogueEntry(**item) for item in raw]
        except Exception:
            return []

    def append(self, entries: list[CatalogueEntry]) -> None:
        existing = self.load()
        all_entries = existing + entries
        with open(self.path, "w") as f:
            json.dump([e.model_dump() for e in all_entries], f, indent=2)

    def find_similar(self, intent: str, top_n: int = 3) -> list[CatalogueEntry]:
        entries = self.load()
        if not entries:
            return []
        keywords = set(intent.lower().split())
        scored: list[tuple[int, CatalogueEntry]] = []
        for entry in entries:
            entry_words = set(entry.intent.lower().split())
            score = len(keywords & entry_words)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_n]]

    def build_context_string(self, entries: list[CatalogueEntry]) -> str:
        if not entries:
            return ""
        lines = ["Past successful charts for similar intents:"]
        for e in entries:
            metrics = ", ".join(e.metric_columns)
            dims = ", ".join(e.dimension_columns) if e.dimension_columns else "none"
            worked = "worked well" if e.worked_well else "partial success"
            lines.append(
                f"  - '{e.intent}' → {e.viz_type}, metric: {metrics}, "
                f"groupby: {dims}, time: {e.time_column or 'none'} ({worked})"
            )
            if e.notes:
                lines.append(f"    note: {e.notes}")
        return "\n".join(lines)
