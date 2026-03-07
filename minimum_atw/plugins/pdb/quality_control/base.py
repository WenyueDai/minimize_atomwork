from __future__ import annotations

from typing import Iterable


class BaseQualityControl:
    name = ""
    prefix = ""
    prepare_section = "quality_control"

    def run(self, ctx) -> Iterable[dict]:
        raise NotImplementedError

    def available(self, _ctx) -> tuple[bool, str]:
        return True, ""
