# This executes the entire session on workstation under its own system UID.
# It consumes the existing model peer. It starts no second GPU service.
# Pass pinned lanectlSrc, residentModelPeerAddress and the PUBLIC
# residentModelPeerCertificate via specialArgs. Keep real LAN details in the host repo.
{ lib, pkgs, lanectlSrc, residentModelPeerAddress, residentModelPeerCertificate, ... }:
let
  peerHost = if lib.hasInfix ":" residentModelPeerAddress then "[${residentModelPeerAddress}]" else residentModelPeerAddress;
  residentPackage = pkgs.callPackage ./package.nix {
    python3Packages = pkgs.python313Packages;
    src = lanectlSrc;
  };
in {
  services.lanectlResident = {
    enable = lib.mkDefault false;
    executionEnabled = lib.mkDefault false;
    python = pkgs.python313.withPackages (_: [ residentPackage ]);
    opencodePackage = pkgs.opencode;
    residentId = "writer-one";
    route = "local/worker-fast";
    eventStateDir = "/var/lib/lanectl-resident-control/receipt-log";
    gateway = {
      upstreamBaseUrl = "https://${peerHost}:8021/v1";
      credentialFile = "/run/secrets/resident-local-model-peer-token";
      caFile = residentModelPeerCertificate;
      allowedTcpDestinations = [ { address = residentModelPeerAddress; port = 8021; } ];
      maxRequestsPerWindow = null; # No monetary/request allowance for local inference.
    };
  };
}
