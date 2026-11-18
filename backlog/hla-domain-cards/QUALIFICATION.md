# Active domain-card qualification

## Observable product contract

The public `GET /reports/domain-cards` response contains exactly one card each
for Finance, Utilities and Homelab. Card membership follows the active
source-owning packs, independent of row counts. Each card exposes its
`domain_key`, headline indicators, a chronological series where comparison is
supported, and one highest-priority open action with a stable source key. The
headline, trend and action states are independent. Successful empty, unavailable
or unknown coverage, an observed numerical zero, insufficient historical
observations, and no open actions must be distinguishable. A missing or unknown
value cannot be replaced with a placeholder numeric zero.

The two monetary cards use ISO currency as the unit and month as the period.
Finance uses observed monthly net. Utilities uses billed totals. For each
denomination, the headline is its last observed period and the series contains
the actual comparable periods. A billed zero belongs in both headline and
trend. A newer usage-only period does not become a monetary point. Fixtures use
gaps, differently recent currencies, and a single-point case.

The Homelab metric counts distinct observed services whose latest known state is
degraded or stopped. Its headline exposes the number of known services and the
actual observation time. Unknown states do not contribute a healthy zero. Trends
use actual run IDs and observed timestamps from service-health observations.
An older and newer sample must have identical full observed service IDs and
known states for each of those services to be comparable. Different same-sized
cohorts, identical known subsets with shared or differing unknown IDs, one point,
and all unknown states exercise the no-comparison path. A known running-only sample is observed zero.
There is no configured inventory, assumed collection cadence or interpolation.

Top action priority is 3, then 2, then 1. In the existing action streams the
card identifies the correct source-domain action instead of pulling a higher
priority action from another domain. Nonstandard persisted priorities cannot
outrank valid priorities. The negative fixture mutates ranks on source-derived
actions after refresh to model malformed persisted rows. For service health, declared criticality
maps critical to 3, standard to 2 and background to 1 in this presentation.
Unrecognized criticality is neutral. Service-ID tie ordering is independent of
the display name and ingestion order. Fixture action controls derive Finance
and Utilities attention through the existing supported source loaders.

## Required qualification

Overlay exactly the files in `release.toml` onto a clean candidate. Record the
production parent, qualification child, criterion hashes, and the exact
qualification-only diff. All other paths must match the production parent.
Run ordinary acceptance and the full real PostgreSQL integration target:

```sh
make test-target TEST='tests/test_acc_domain_cards.py --tb=short'
```

Set `DOMAIN_CARDS_POSTGRES_DSN` to an isolated PostgreSQL instance for the full
target. The fixtures create their own schemas, publish registered relations and
clear the supporting warehouse marts and facts before strict reads. A separate
case leaves valid warehouse data while the PostgreSQL relation is absent. A
partial-publication case confirms that missing Homelab current data leaves
observed Finance and Utilities cards intact. The
source-only guard must pass on both base and candidate so loader or fixture
breakage cannot qualify a negative.

From the clean candidate root, run the owner browser qualifier with a new
absolute report directory under `DOMAIN_CARDS_REPORT_DIR`:

```sh
bash /absolute/path/to/hla-domain-cards/run-domain-cards-ui.sh
```

Use the candidate's checked-in development setup and run inside the project
namespace. The test uses actual Next and Playwright in three strict PUBLISHED
scenarios with disposable schemas: rich observations, a successful empty
publication, and unavailable publications with populated warehouse sources.
The fixture server and frontend must both start before browser assertions.
Retain the three Playwright JSON reports and logs together with candidate and
criteria bindings. Only exact executed passes qualify. The group exposes one
accessible article per active domain, visible observed headlines/trends and
the winning source action, with distinct copy for empty and unavailable. The
retained attention panel must not show its all-clear message when the published
attention relation is unavailable.
