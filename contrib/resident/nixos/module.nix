{ config, lib, pkgs, ... }:
let
  inherit (lib) mkEnableOption mkIf mkOption types;
  cfg = config.services.lanectlResident;
  python = "${cfg.python}/bin/python";
  zeros = lib.concatStrings (lib.replicate 64 "0");
  profileDir = "/etc/lanectl/resident";
  gatewaySocket = "/run/lanectl-resident-model/model.sock";
  nativeTemplate = pkgs.writeText "resident-native-template.json" (builtins.toJSON {
    schema = "lanectl.resident-native/v1";
    resident_id = cfg.residentId;
    route = cfg.route;
    workspace = cfg.workspace;
    context_scope = { resident = cfg.residentId; project = cfg.project; branch = cfg.branch; };
    artifact_roots = cfg.artifactRoots;
    gateway_base_url = "http://127.0.0.1:${toString cfg.gateway.port}/v1";
    gateway_socket = gatewaySocket;
    opencode_executable = "${cfg.opencodePackage}/bin/opencode";
    opencode_sha256 = zeros;
    opencode_config = "${profileDir}/opencode/opencode.json";
    opencode_config_sha256 = zeros;
    runtime_root = cfg.runtimeRoot;
    tool_path = map (package: "${package}/bin") cfg.toolPackages;
    timeout_s = cfg.nativeTimeoutSeconds;
    max_output_bytes = 2097152;
    context_tokens = cfg.contextTokens;
    output_tokens = cfg.outputTokens;
  });
  opencodeConfig = pkgs.runCommand "resident-opencode-config" { } ''
    mkdir -p "$out"
    ${python} -I -m lanectl.resident_native render-config \
      --config ${nativeTemplate} > "$out/opencode.json"
  '';
  nativeProfile = pkgs.runCommand "resident-native.json" { } ''
    ${python} -I - ${nativeTemplate} ${opencodeConfig}/opencode.json "$out" <<'PY'
    import hashlib, json, pathlib, sys
    source, config, output = map(pathlib.Path, sys.argv[1:])
    profile = json.loads(source.read_text())
    profile["opencode_config"] = str(config)
    profile["opencode_sha256"] = hashlib.sha256(pathlib.Path(profile["opencode_executable"]).read_bytes()).hexdigest()
    profile["opencode_config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
    output.write_text(json.dumps(profile, sort_keys=True) + "\n")
    PY
  '';
  launchConfig = pkgs.writeText "resident-systemd.json" (builtins.toJSON {
    schema = "lanectl.resident-systemd/v1";
    worker_user = cfg.workerUser;
    worker_group = cfg.workerUser;
    workspace = cfg.workspace;
    runtime_root = cfg.runtimeRoot;
    control_root = cfg.controlRoot;
    tool_unit = "lanectl-resident-tools.service";
    coordinator_unit = "lanectl-resident-episode.service";
    systemd_run = "${pkgs.systemd}/bin/systemd-run";
    systemctl = "${pkgs.systemd}/bin/systemctl";
    env_executable = "${pkgs.coreutils}/bin/env";
    # Store paths, not mutable /etc aliases, bind the full native runtime into
    # the bridge hash and therefore into the outer qualification recipe.
    native_argv = [ python "-I" "-m" "lanectl.resident_native" "run" "--config" "${nativeProfile}" ];
    timeout_s = cfg.toolRuntimeSeconds;
    memory_max = cfg.memoryMax;
    tasks_max = cfg.tasksMax;
    cpu_quota = cfg.cpuQuota;
    gateway_port = cfg.gateway.port;
    gateway_socket = gatewaySocket;
    gateway_config = "${gatewayConfig}";
    host_policy_sha256 = builtins.hashString "sha256" (builtins.toJSON {
      credential_source = cfg.gateway.credentialFile;
      firewall_rules = outputRules;
      nft_backend = nftBackend;
    });
  });
  launcher = pkgs.writeShellScript "resident-systemd-launcher" ''
    if [ "$#" -eq 0 ]; then
      exec ${python} -I -m lanectl.resident_systemd launch --config ${launchConfig}
    elif [ "$#" -eq 1 ] && [ "$1" = cleanup ]; then
      exec ${python} -I -m lanectl.resident_systemd cleanup --config ${launchConfig}
    fi
    exit 2
  '';
  residentTemplate = pkgs.writeText "resident-profile-template.json" (builtins.toJSON {
    schema = "lanectl.resident-profile/v1";
    resident_id = cfg.residentId;
    workspace = cfg.workspace;
    state_dir = "${cfg.controlRoot}/checkpoints";
    context_scope = { resident = cfg.residentId; project = cfg.project; branch = cfg.branch; };
    artifact_roots = cfg.artifactRoots;
    require_source_recheck = true;
    execution = {
      enabled = cfg.executionEnabled;
      route = cfg.route;
      argv = [ "${launcher}" ];
      timeout_s = 2700;
      executable_sha256 = zeros;
      cleanup_argv = [ "${launcher}" "cleanup" ];
      cleanup_executable_sha256 = zeros;
      qualification_file = cfg.qualificationFile;
      qualification_sha256 = cfg.qualificationSha256;
    };
  });
  residentProfile = pkgs.runCommand "resident-profile.json" { } ''
    ${python} -I - ${residentTemplate} ${launcher} "$out" <<'PY'
    import hashlib, json, pathlib, sys
    source, launcher, output = map(pathlib.Path, sys.argv[1:])
    profile = json.loads(source.read_text())
    digest = hashlib.sha256(launcher.read_bytes()).hexdigest()
    profile["execution"]["executable_sha256"] = digest
    profile["execution"]["cleanup_executable_sha256"] = digest
    output.write_text(json.dumps(profile, sort_keys=True) + "\n")
    PY
  '';
  dispatchConfig = pkgs.writeText "resident-dispatch.json" (builtins.toJSON {
    schema = "lanectl.resident-dispatch/v1";
    python_executable = python;
    profile = "${residentProfile}";
    event_state_dir = cfg.eventStateDir;
    admission_dir = "${cfg.controlRoot}/inbox";
    request_file = "${cfg.controlRoot}/inbox/request.json";
  });
  gatewayConfig = pkgs.writeText "resident-gateway.json" (builtins.toJSON {
    schema = "lanectl.resident-gateway/v1";
    route = cfg.route;
    upstream_base_url = cfg.gateway.upstreamBaseUrl;
    listen_port = cfg.gateway.port;
    listen_socket = gatewaySocket;
    credential_name = "upstream-token";
    session_id = cfg.residentId;
    state_file = "${cfg.gateway.stateDir}/requests.sqlite3";
    ca_file = if cfg.gateway.caFile == null then null else "${cfg.gateway.caFile}";
    max_request_bytes = 524288;
    max_response_bytes = 8388608;
    max_output_tokens = cfg.outputTokens;
    timeout_s = 900;
    max_requests_per_window = cfg.gateway.maxRequestsPerWindow;
    window_s = cfg.gateway.windowSeconds;
  });
  addressFamily = address: if lib.hasInfix ":" address then "ip6" else "ip";
  nftIdentity = name:
    let uid = config.users.users.${name}.uid;
    in if uid == null then ''"${name}"'' else toString uid;
  gatewayDestinations = lib.concatMapStringsSep "\n" (destination:
    ''meta skuid ${nftIdentity cfg.gatewayUser} ${addressFamily destination.address} daddr ${destination.address} tcp dport ${toString destination.port} accept''
  ) cfg.gateway.allowedTcpDestinations;
  dnsRules = lib.concatMapStringsSep "\n" (address:
    ''meta skuid ${nftIdentity cfg.gatewayUser} ${addressFamily address} daddr ${address} meta l4proto { tcp, udp } th dport 53 accept''
  ) cfg.gateway.dnsServers;
  outputRules = [
    # Defense in depth for an accidentally host-networked process using the
    # worker UID; intended tools have their own network namespace and loopback.
    ''meta skuid ${nftIdentity cfg.workerUser} counter reject''
  ] ++ lib.filter (line: line != "") (lib.splitString "\n" (dnsRules + "\n" + gatewayDestinations))
    ++ lib.optionals cfg.gateway.allowPublicHttps [
      ''meta skuid ${nftIdentity cfg.gatewayUser} ip daddr != { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.168.0.0/16, 198.18.0.0/15, 224.0.0.0/4, 240.0.0.0/4 } tcp dport 443 accept''
      ''meta skuid ${nftIdentity cfg.gatewayUser} ip6 daddr != { ::/128, ::1/128, fc00::/7, fe80::/10, ff00::/8 } tcp dport 443 accept''
    ] ++ [ ''meta skuid ${nftIdentity cfg.gatewayUser} counter reject'' ];
  nftBackend = config.networking.nftables.enable;
  firewallOwnerUnit = if nftBackend then "nftables.service" else "firewall.service";
  # An independent nft table coexists with the workstation's iptables firewall.
  # Do NOT enable networking.nftables globally: its existing modelPeer module
  # intentionally asserts the iptables ingress implementation.
  firewallRules = pkgs.writeText "lanectl-resident.nft" ''
    add table inet lanectl_resident
    flush table inet lanectl_resident
    add chain inet lanectl_resident output { type filter hook output priority -5; policy accept; }
    ${lib.concatMapStringsSep "\n" (rule: "add rule inet lanectl_resident output " + rule) outputRules}
  '';
  privateUser = {
    isSystemUser = true;
    createHome = false;
    home = "/var/empty";
    shell = "${pkgs.shadow}/bin/nologin";
    extraGroups = [ ];
  };
in {
  options.services.lanectlResident = {
    enable = mkEnableOption "isolated bounded resident execution (does not install a scheduler)";
    executionEnabled = mkOption { type = types.bool; default = false; description = "Candidate profile execution switch; a real matching qualification receipt is still required."; };
    python = mkOption { type = types.package; description = "Pinned Python >=3.13 environment importing lanectl, resident_native, resident_gateway and resident_systemd."; };
    opencodePackage = mkOption { type = types.package; description = "Pinned OpenCode >=2.2.3 package with bin/opencode."; };
    residentId = mkOption { type = types.strMatching "[A-Za-z0-9][A-Za-z0-9_.:-]*"; default = "writer-one"; };
    project = mkOption { type = types.str; default = "stories"; };
    branch = mkOption { type = types.str; default = "canon"; };
    artifactRoots = mkOption { type = types.listOf types.str; default = [ "drafts" "canon" ]; };
    route = mkOption { type = types.enum [ "opencode-go/deepseek-v4.1-flash" "local/worker-fast" ]; };
    workerUser = mkOption { type = types.strMatching "resident-[a-z0-9_-]+"; default = "resident-worker"; };
    gatewayUser = mkOption { type = types.strMatching "resident-[a-z0-9_-]+"; default = "resident-model"; };
    workspace = mkOption { type = types.str; default = "/var/lib/lanectl-resident/workspace"; };
    runtimeRoot = mkOption { type = types.str; default = "/var/lib/lanectl-resident/runtime"; };
    controlRoot = mkOption { type = types.str; default = "/var/lib/lanectl-resident-control"; };
    eventStateDir = mkOption { type = types.str; description = "Explicit existing/commissioned local receipt log root. Never replace a selected served authority with a fresh local directory."; };
    qualificationFile = mkOption { type = types.str; default = "${profileDir}/qualification.json"; };
    qualificationSha256 = mkOption { type = types.strMatching "[0-9a-f]{64}"; default = zeros; };
    toolPackages = mkOption { type = types.listOf types.package; default = with pkgs; [ bash coreutils git ripgrep python313 ]; };
    nativeTimeoutSeconds = mkOption { type = types.ints.between 1 2600; default = 2400; };
    toolRuntimeSeconds = mkOption { type = types.ints.between 1 2670; default = 2460; };
    memoryMax = mkOption { type = types.strMatching "[1-9][0-9]*[MG]"; default = "8G"; };
    tasksMax = mkOption { type = types.ints.between 16 4096; default = 256; };
    cpuQuota = mkOption { type = types.strMatching "[1-9][0-9]*%"; default = "200%"; };
    contextTokens = mkOption { type = types.ints.between 1024 262144; default = 32768; };
    outputTokens = mkOption { type = types.ints.between 1 8192; default = 8192; };
    gateway = {
      port = mkOption { type = types.ints.between 1024 65535; default = 18021; };
      upstreamBaseUrl = mkOption { type = types.str; };
      credentialFile = mkOption { type = types.str; description = "Runtime secret file loaded by systemd; never a secret value or a Nix store path."; };
      caFile = mkOption { type = types.nullOr types.path; default = null; description = "Public CA/pinned peer certificate, never its private key."; };
      stateDir = mkOption { type = types.str; default = "/var/lib/lanectl-resident-model"; };
      maxRequestsPerWindow = mkOption { type = types.nullOr (types.ints.between 1 100000); default = null; };
      windowSeconds = mkOption { type = types.ints.between 60 86400; default = 3600; };
      dnsServers = mkOption { type = types.listOf types.str; default = [ ]; description = "Exact resolver IPs used by the gateway host; workers receive no DNS access."; };
      allowPublicHttps = mkOption { type = types.bool; default = false; description = "Allow the trusted fixed-origin Go gateway outbound public TCP443; workers remain loopback-port-only."; };
      allowedTcpDestinations = mkOption {
        default = [ ];
        type = types.listOf (types.submodule { options = {
          address = mkOption { type = types.str; };
          port = mkOption { type = types.ints.between 1 65535; };
        }; });
      };
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = !nftBackend || (config.users.users.${cfg.workerUser}.uid != null
          && config.users.users.${cfg.gatewayUser}.uid != null);
        message = "Declare fixed resident user UIDs for build-time nftables validation.";
      }
      { assertion = lib.versionAtLeast pkgs.systemd.version "257"; message = "Resident tools require systemd >=257 for disconnected private temporary storage."; }
      { assertion = cfg.workerUser != cfg.gatewayUser; message = "Resident worker and credential gateway require different UIDs."; }
      { assertion = cfg.gateway.port == 18021; message = "The private native model relay uses the fixed loopback port 18021."; }
      { assertion = lib.all (path: lib.hasPrefix "/var/lib/" path) [ cfg.workspace cfg.runtimeRoot cfg.controlRoot cfg.eventStateDir cfg.gateway.stateDir ]; message = "Resident private data roots must live below /var/lib; only workspace/runtime are rebound into the worker's private /var."; }
      { assertion = cfg.nativeTimeoutSeconds < cfg.toolRuntimeSeconds; message = "Native deadline must leave cgroup cleanup time before the outer episode deadline."; }
      { assertion = cfg.outputTokens < cfg.contextTokens; message = "Resident output budget must fit context."; }
      { assertion = cfg.route != "opencode-go/deepseek-v4.1-flash" || cfg.gateway.maxRequestsPerWindow != null; message = "Go requires an explicit persistent gateway request allowance."; }
      { assertion = !lib.hasPrefix "/nix/store/" cfg.gateway.credentialFile; message = "The upstream token must be a runtime systemd credential, never a Nix store file."; }
      { assertion = lib.all (address: builtins.match "[0-9a-fA-F:./]+" address != null) (cfg.gateway.dnsServers ++ map (destination: destination.address) cfg.gateway.allowedTcpDestinations); message = "Gateway firewall destinations must be numeric IPs/CIDRs."; }
      { assertion = config.users.users.${cfg.workerUser}.extraGroups == [ ] && config.users.users.${cfg.gatewayUser}.extraGroups == [ ]; message = "Resident identities must not inherit docker, wheel, developers or regular-user groups."; }
    ];

    users.groups.${cfg.workerUser} = { };
    users.groups.${cfg.gatewayUser} = { };
    users.users.${cfg.workerUser} = privateUser // { group = cfg.workerUser; };
    users.users.${cfg.gatewayUser} = privateUser // { group = cfg.gatewayUser; };
    systemd.tmpfiles.rules = [
      "d /var/lib/lanectl-resident 0711 root root - -"
      "d ${cfg.workspace} 0700 ${cfg.workerUser} ${cfg.workerUser} - -"
      "d ${cfg.workspace}/.lanectl-resident-results 0700 ${cfg.workerUser} ${cfg.workerUser} - -"
      "d ${cfg.runtimeRoot} 0700 ${cfg.workerUser} ${cfg.workerUser} - -"
      "d ${cfg.controlRoot} 0700 root root - -"
      "d ${cfg.controlRoot}/inbox 0700 root root - -"
      "d ${cfg.controlRoot}/checkpoints 0700 root root - -"
      "d ${cfg.eventStateDir} 0700 root root - -"
      "d ${cfg.gateway.stateDir} 0700 ${cfg.gatewayUser} ${cfg.gatewayUser} - -"
      "d /run/lanectl-resident-model 0755 root root - -"
    ];
    environment.etc = {
      "lanectl/resident/profile.json".source = residentProfile;
      "lanectl/resident/native.json".source = nativeProfile;
      "lanectl/resident/opencode/opencode.json".source = "${opencodeConfig}/opencode.json";
      "lanectl/resident/gateway.json".source = gatewayConfig;
      "lanectl/resident/dispatch.json".source = dispatchConfig;
      "lanectl/resident/systemd.json".source = launchConfig;
    };

    # On the devbox the host already owns an nft ruleset. Register this table
    # there so a host ruleset reload preserves the UID boundary atomically.
    networking.nftables.tables.lanectl_resident = mkIf nftBackend {
      family = "inet";
      content = ''
        chain output {
          type filter hook output priority -5; policy accept;
          ${lib.concatStringsSep "\n" outputRules}
        }
      '';
    };

    systemd.services.lanectl-resident-firewall = {
      description = "Resident UID and destination-port firewall";
      before = [ "lanectl-resident-model.service" "lanectl-resident-episode.service" ];
      after = [ firewallOwnerUnit ];
      requires = lib.optionals nftBackend [ firewallOwnerUnit ];
      partOf = [ firewallOwnerUnit ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = if nftBackend then "${pkgs.nftables}/bin/nft list table inet lanectl_resident" else "${pkgs.nftables}/bin/nft -f ${firewallRules}";
        ExecReload = if nftBackend then "${pkgs.nftables}/bin/nft list table inet lanectl_resident" else "${pkgs.nftables}/bin/nft -f ${firewallRules}";
        User = "root";
        CapabilityBoundingSet = [ "CAP_NET_ADMIN" ];
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
      } // lib.optionalAttrs (!nftBackend) {
        ExecStop = "${pkgs.nftables}/bin/nft delete table inet lanectl_resident";
      };
    };

    systemd.services.lanectl-resident-model = {
      description = "Resident fixed model capability (separate credential identity)";
      requires = [ "lanectl-resident-firewall.service" "lanectl-resident-model.socket" ];
      bindsTo = [ "lanectl-resident-firewall.service" ];
      after = [ "network-online.target" "lanectl-resident-firewall.service" "lanectl-resident-model.socket" ];
      wants = [ "network-online.target" ];
      environment.SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
      serviceConfig = {
        Type = "exec";
        User = cfg.gatewayUser;
        Group = cfg.gatewayUser;
        ExecStart = "${python} -I -m lanectl.resident_gateway run --config ${gatewayConfig}";
        LoadCredential = [ "upstream-token:${cfg.gateway.credentialFile}" ];
        Restart = "on-failure";
        RestartSec = 5;
        UMask = "0077";
        NoNewPrivileges = true;
        CapabilityBoundingSet = [ ];
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        PrivateIPC = true;
        ProtectProc = "invisible";
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectKernelLogs = true;
        ProtectControlGroups = true;
        RestrictSUIDSGID = true;
        RestrictNamespaces = true;
        RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
        ReadWritePaths = [ cfg.gateway.stateDir ];
        InaccessiblePaths = [ cfg.workspace cfg.runtimeRoot cfg.controlRoot "-/run/user" "-/run/docker.sock" "-/run/libvirt" "-/run/dbus/system_bus_socket" "-/run/systemd/private" "-/projects" ];
        MemoryMax = "512M";
        TasksMax = 64;
      };
    };

    systemd.sockets.lanectl-resident-model = {
      description = "Resident's sole host model capability socket";
      requires = [ "lanectl-resident-firewall.service" ];
      bindsTo = [ "lanectl-resident-firewall.service" ];
      after = [ "systemd-tmpfiles-setup.service" "lanectl-resident-firewall.service" ];
      listenStreams = [ gatewaySocket ];
      socketConfig = {
        SocketUser = cfg.gatewayUser;
        SocketGroup = cfg.workerUser;
        SocketMode = "0660";
        DirectoryMode = "0755";
        RemoveOnStop = true;
      };
    };

    systemd.services.lanectl-resident-episode = {
      description = "One protected resident admission and bounded episode";
      # No wantedBy/timer/path unit: the existing owner publishes a protected
      # admission and starts this unit. Type=exec lets the transient tool unit
      # order After/BindsTo this active coordinator without a oneshot deadlock.
      requires = [ "lanectl-resident-model.service" "lanectl-resident-firewall.service" ];
      bindsTo = [ "lanectl-resident-firewall.service" ];
      after = [ "lanectl-resident-model.service" "lanectl-resident-firewall.service" ];
      serviceConfig = {
        Type = "exec";
        User = "root";
        Group = "root";
        ExecStart = "${python} -I -m lanectl.resident_systemd episode --config ${dispatchConfig}";
        ExecStopPost = "${launcher} cleanup";
        Restart = "no";
        RuntimeMaxSec = 2760;
        TimeoutStopSec = 35;
        KillMode = "control-group";
        UMask = "0077";
        NoNewPrivileges = true;
        CapabilityBoundingSet = [ "CAP_CHOWN" "CAP_DAC_OVERRIDE" "CAP_FOWNER" ];
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        ReadWritePaths = [ cfg.workspace cfg.runtimeRoot cfg.controlRoot cfg.eventStateDir ];
        InaccessiblePaths = [ cfg.gateway.stateDir "-/run/user" "-/run/docker.sock" "-/run/libvirt" ];
        RestrictAddressFamilies = [ "AF_UNIX" ];
        MemoryMax = "512M";
        TasksMax = 64;
      };
    };
  };
}
