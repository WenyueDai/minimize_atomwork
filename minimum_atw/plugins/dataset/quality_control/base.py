from __future__ import annotations

from typing import Iterable


class BaseDatasetQualityControl:
    name = ""
    prefix = ""
    extension_class = "dataset_quality_control"
    analysis_category = "dataset_quality_control"
    prepare_section = "dataset_quality_control"

    def run(self, ctx) -> Iterable[dict]:
        raise NotImplementedError

    def available(self, _ctx) -> tuple[bool, str]:
        return True, ""
