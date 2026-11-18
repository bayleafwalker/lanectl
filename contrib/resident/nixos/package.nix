{ lib, python3Packages, src }:
python3Packages.buildPythonPackage {
  pname = "lanectl";
  version = "0.2.15";
  inherit src;
  pyproject = true;
  build-system = [ python3Packages.hatchling ];
  nativeCheckInputs = with python3Packages; [ pytestCheckHook hypothesis ];
  # The Nix sandbox lacks the host machine identity used by coordinator
  # tests. The installed-interpreter and complete resident tests are also
  # required on the target host.
  enabledTestPaths = [
    "tests/resident/test_gateway.py"
    "tests/resident/test_gateway_review.py"
    "tests/resident/test_native.py"
    "tests/resident/test_systemd.py"
  ];
  disabledTests = [ "test_isolated_module_start_ignores_workspace_python_shadow" ];
  pythonImportsCheck = [
    "lanectl.resident" "lanectl.resident_native"
    "lanectl.resident_gateway" "lanectl.resident_systemd"
  ];
  meta = {
    description = "Pinned lanectl resident runner and protected host adapters";
    platforms = lib.platforms.linux;
  };
}
