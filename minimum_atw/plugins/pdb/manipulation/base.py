from __future__ import annotations

from typing import Iterable


class BaseStructureManipulation:
    name = ""
    prefix = ""
    prepare_section = "structure"

    def run(self, ctx) -> Iterable[dict]:
        raise NotImplementedError

    def available(self, _ctx) -> tuple[bool, str]:
        return True, ""

    def plugin_params(self, ctx) -> dict:
        return dict(getattr(ctx.config, "plugin_params", {}).get(self.name, {}))
