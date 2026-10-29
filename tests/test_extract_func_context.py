import tempfile
import unittest
from pathlib import Path

from extract_functions import extract_func


class ExtractFunctionContextTests(unittest.TestCase):
    def build_index(self, files):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        for relative_path, source in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return extract_func.build_repository_index(root)

    @staticmethod
    def context(index, path, name, class_name=None):
        target = extract_func.match_target(
            {"src_file": path, "name": name, "class_name": class_name}, index
        )
        return extract_func.build_context_for_target(target, index)

    def test_python_constructor_same_file_test_fields_and_types(self):
        index = self.build_index({
            "module.py": """
class Payload:
    pass


class Widget:
    kind: str

    def __init__(self, payload: Payload):
        self.payload = payload


def make_widget():
    return Widget(Payload())


def test_make_widget():
    return make_widget()
""".lstrip()
        })

        constructor = self.context(index, "module.py", "__init__", "Widget")
        self.assertTrue(any("def make_widget" in item["code"]
                            for item in constructor["direct_callers"]))
        self.assertTrue(any("class Payload" in item["code"]
                            for item in constructor["related_types"]))
        self.assertTrue(any("kind: str" in item["code"]
                            for item in constructor["class_context"]))

        make_widget = self.context(index, "module.py", "make_widget")
        self.assertTrue(any("def test_make_widget" in item["code"]
                            for item in make_widget["related_tests"]))
        self.assertTrue(any("def __init__" in item["code"]
                            for item in make_widget["dependencies"]))

    def test_javascript_default_import_alias_is_resolved(self):
        index = self.build_index({
            "source.js": """
export default function work(value) {
  return value + 1;
}

export function helper(value) {
  return value - 1;
}
""".lstrip(),
            "consumer.js": """
import renamedWork from './source.js';

export function caller() {
  return renamedWork(1);
}
""".lstrip(),
        })

        work = self.context(index, "source.js", "work")
        self.assertTrue(any("function caller" in item["code"]
                            for item in work["direct_callers"]))

        caller = self.context(index, "consumer.js", "caller")
        dependency_code = [item["code"] for item in caller["dependencies"]]
        self.assertEqual(1, len(dependency_code))
        self.assertIn("function work", dependency_code[0])

    def test_function_local_import_does_not_leak_to_other_functions(self):
        index = self.build_index({
            "target.py": "def work():\n    return 1\n",
            "consumer.py": """
def valid_caller():
    from target import work
    return work()


def import_owner_only():
    from target import work
    return 0


def invalid_caller():
    return work()
""".lstrip(),
        })

        work = self.context(index, "target.py", "work")
        caller_code = [item["code"] for item in work["direct_callers"]]
        self.assertEqual(1, len(caller_code))
        self.assertIn("def valid_caller", caller_code[0])

    def test_receiver_type_evidence_is_limited_to_caller_scope(self):
        index = self.build_index({
            "Service.java": """
class Service {
    void run() {}
}
""".lstrip(),
            "Consumer.java": """
class Consumer {
    void unrelated() {
        Service client = null;
    }

    void wrong() {
        client.run();
    }

    void right() {
        Service service = null;
        service.run();
    }
}
""".lstrip(),
        })

        run = self.context(index, "Service.java", "run", "Service")
        caller_code = [item["code"] for item in run["direct_callers"]]
        self.assertEqual(1, len(caller_code))
        self.assertIn("void right", caller_code[0])

    def test_leading_comments_do_not_cross_a_blank_line(self):
        index = self.build_index({
            "module.py": "# unrelated comment\n\ndef target():\n    return 1\n"
        })
        target = extract_func.match_target(
            {"src_file": "module.py", "name": "target"}, index
        )
        self.assertEqual("", target.leading_comments)

    def test_imports_are_filtered_only_against_target_function(self):
        index = self.build_index({
            "module.py": """
import math
import decimal


def target(value):
    return math.floor(value)


def caller():
    decimal.Decimal('1.0')
    return target(1.5)
""".lstrip()
        })

        context = self.context(index, "module.py", "target")
        self.assertEqual(["import math"], context["target_function"]["imports"])

    def test_javascript_object_property_named_function_is_collected(self):
        index = self.build_index({
            "module.js": """
const api = {
  relative: function relative(from, to) {
    return from + to;
  }
};
""".lstrip()
        })
        target = extract_func.match_target(
            {"src_file": "module.js", "name": "relative", "start_line": 2}, index
        )
        self.assertEqual("relative", target.name)


if __name__ == "__main__":
    unittest.main()
