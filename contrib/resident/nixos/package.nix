{ lib, python3Packages, src }:
python3Packages.buildPythonPackage {
  pname = "lanectl-resident";
  version = "0.2.15-resident";
  inherit src;
  pyproject = true;
  build-system = [ python3Packages.hatchling ];
  nativeCheckInputs = with python3Packages; [ pytestCheckHook hypothesis ];
  # These protocol/adapter tests fit a Nix build sandbox. The complete suite
  # also requires a running systemd user bus and remains a separate required
  # target-host/CI gate; do not waive it based on this package build.
  pytestFlagsArray = [ "tests/resident" ];
  pythonImportsCheck = [
    "lanectl.resident" "lanectl.resident_native"
    "lanectl.resident_gateway" "lanectl.resident_systemd"
  ];
  meta = {
    description = "Pinned lanectl resident runner and protected host adapters";
    platforms = lib.platforms.linux;
  };
}
