import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "generate_ts_schema.py"
SPEC = importlib.util.spec_from_file_location("generate_ts_schema", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
generate_ts_schema = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_ts_schema)


class SchemaGenerationTests(unittest.TestCase):
    def test_python_generator_failure_is_fatal(self):
        error = subprocess.CalledProcessError(1, ["python", "generator.py"])

        with (
            patch.object(generate_ts_schema, "generate_typescript_schema", return_value="schema"),
            patch.object(Path, "write_text"),
            patch("subprocess.run", side_effect=error) as run,
            patch("builtins.print"),
            self.assertRaises(SystemExit) as raised,
        ):
            generate_ts_schema.main()

        self.assertEqual(raised.exception.code, 1)
        self.assertTrue(run.call_args.kwargs["check"])


if __name__ == "__main__":
    unittest.main()
