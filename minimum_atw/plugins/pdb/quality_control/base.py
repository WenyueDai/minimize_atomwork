from __future__ import annotations

from ..manipulation.base import BaseStructureManipulation


class BaseQualityControl(BaseStructureManipulation):
    prepare_section = "quality_control"
