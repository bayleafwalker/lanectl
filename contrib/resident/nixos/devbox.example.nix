# Pass a pinned lanectlSrc source through specialArgs. Import module.nix too.
{ config, lib, pkgs, lanectlSrc, ... }:
let
  residentPackage = pkgs.callPackage ./package.nix {
    python3Packages = pkgs.python313Packages;
    src = lanectlSrc;
  };
in {
  services.lanectlResident = {
    enable = lib.mkDefault false; # Opt in only after the host integration/checks in README.
    executionEnabled = lib.mkDefault false;
    python = pkgs.python313.withPackages (_: [ residentPackage ]);
    opencodePackage = pkgs.opencode;
    residentId = "writer-one";
    route = "opencode-go/deepseek-v4.1-flash";
    eventStateDir = "/var/lib/lanectl-resident-control/receipt-log";
    gateway = {
      upstreamBaseUrl = "https://opencode.ai/inference/go/openai/v1";
      credentialFile = "/run/secrets/resident-opencode-go-token";
      allowPublicHttps = true;
      # The current devbox's explicit resolver owner; retain its configured list.
      dnsServers = config.profiles.agentEgress.dnsServers;
      maxRequestsPerWindow = 120; # Explicit allowance, not a claim of entitlement.
      windowSeconds = 3600;
    };
  };
}
