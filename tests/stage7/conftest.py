"""Stage-7 fixtures (planner-owned): the seed estate, exposed by assignment so tests never import it."""
from tests.seed import test_end_to_end as seed

estate = seed.estate
