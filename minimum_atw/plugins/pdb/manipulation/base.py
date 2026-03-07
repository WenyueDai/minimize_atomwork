from __future__ import annotations

from typing import Iterable


class BaseStructureManipulation:
    name = ""
    prefix = ""
    extension_class = "pdb_manipulation"
    analysis_category = "structure_manipulation"
    prepare_section = "structure"

    def run(self, ctx) -> Iterable[dict]:
        raise NotImplementedError

    def available(self, _ctx) -> tuple[bool, str]:
        return True, ""
