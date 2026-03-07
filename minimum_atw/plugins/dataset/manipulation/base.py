from __future__ import annotations

from typing import Iterable


class BaseDatasetManipulation:
    name = ""
    prefix = ""
    extension_class = "dataset_manipulation"
    analysis_category = "dataset_manipulation"
    prepare_section = "dataset"

    def run(self, ctx) -> Iterable[dict]:
        raise NotImplementedError

    def available(self, _ctx) -> tuple[bool, str]:
        return True, ""
