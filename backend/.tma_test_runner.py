import os
import sys
from sqlalchemy.engine import make_url
from app.config.settings import settings

url = make_url(settings.DATABASE_URL)
assert url.host in ("localhost", "127.0.0.1")
assert url.database == "weave_dev_database"
url = url.render_as_string(hide_password=False)
os.environ["TEST_DATABASE_URL"] = url
os.environ["DATABASE_URL"] = url
os.environ["CACHE_ENABLED"] = "false"
settings.DATABASE_URL = url
settings.CACHE_ENABLED = False
import pytest

sys.exit(pytest.main(sys.argv[1:] + ["-p", "no:cacheprovider"]))
