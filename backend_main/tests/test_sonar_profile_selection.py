from pathlib import Path
import sys
import types
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Profile selection does not make HTTP requests.  Supply a tiny placeholder so
# this focused unit test can run in environments that have not installed the
# backend's optional runtime dependencies yet.
sys.modules.setdefault("requests", types.ModuleType("requests"))

from app import config  # noqa: E402
from app.services import sonar_analysis  # noqa: E402


class SonarProfileSelectionTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            name: getattr(config, name)
            for name in (
                "SONAR_PYTHON_URL", "SONAR_PYTHON_TOKEN", "SONAR_PYTHON_USERNAME", "SONAR_PYTHON_PASSWORD",
                "SONAR_C_CPP_URL", "SONAR_C_CPP_TOKEN", "SONAR_C_CPP_USERNAME", "SONAR_C_CPP_PASSWORD",
            )
        }
        config.SONAR_PYTHON_URL = "https://python-sonar.example"
        config.SONAR_PYTHON_TOKEN = "python-token"
        config.SONAR_C_CPP_URL = "https://native-sonar.example:9000"
        config.SONAR_C_CPP_TOKEN = "native-token"

    def tearDown(self):
        for name, value in self.original.items():
            setattr(config, name, value)

    def test_python_files_use_the_python_profile(self):
        profile = sonar_analysis.profile_for_files(["src/service.py", "tests/test_service.py"])

        self.assertEqual(profile.name, "Python")
        self.assertEqual(profile.url, "https://python-sonar.example")
        self.assertEqual(profile.token, "python-token")
        self.assertTrue(sonar_analysis.configured(["src/service.py"]))

    def test_c_and_cpp_files_use_the_native_profile(self):
        profile = sonar_analysis.profile_for_files(["src/main.cpp", "include/main.hpp"])

        self.assertEqual(profile.name, "C/C++")
        self.assertEqual(profile.url, "https://native-sonar.example:9000")
        self.assertEqual(profile.token, "native-token")
        self.assertTrue(sonar_analysis.configured(["src/main.c"]))
