from __future__ import annotations

import unittest

try:
    from minimum_atw.config import Config
except ModuleNotFoundError as exc:
    if exc.name != "pydantic":
        raise
    Config = None


@unittest.skipIf(Config is None, "pydantic is not installed")
class ConfigTests(unittest.TestCase):
    def test_extension_lists_are_trimmed_and_deduplicated(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            plugins=[" identity ", "identity", "", "role_stats"],
            manipulations=[" center_on_origin ", "center_on_origin"],
            dataset_analyses=[" interface_summary ", "interface_summary"],
        )

        self.assertEqual(cfg.plugins, ["identity", "role_stats"])
        self.assertEqual(cfg.manipulations, ["center_on_origin"])
        self.assertEqual(cfg.dataset_analyses, ["interface_summary"])

    def test_roles_and_interface_pairs_are_normalized(self) -> None:
        cfg = Config(
            input_dir="/tmp/in",
            out_dir="/tmp/out",
            roles={" vh ": [" H ", "H", ""], "": ["X"]},
            interface_pairs=[(" vh ", " antigen "), ("vh", "antigen"), ("", "antigen")],
        )

        self.assertEqual(cfg.roles, {"vh": ["H"]})
        self.assertEqual(cfg.interface_pairs, [("vh", "antigen")])


if __name__ == "__main__":
    unittest.main()
