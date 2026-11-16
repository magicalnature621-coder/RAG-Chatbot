# Vercel serverless entry point: exposes the FastAPI app (API + static frontend).
#
# vercel.json rewrites every request to this function as
# /api/index?__path=/<original path>, and the function then sees "/api/index"
# as its path. The wrapper below restores the original path (and the rest of
# the query string) so FastAPI routes the request as if it arrived directly.
import os
import sys
from urllib.parse import parse_qsl, urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import app as fastapi_app  # noqa: E402

PATH_PARAM = "__path"


class _RestoreOriginalPath:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            params = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
            original = [v for k, v in params if k == PATH_PARAM]
            if original:
                path = "/" + original[0].lstrip("/")
                rest = urlencode([(k, v) for k, v in params if k != PATH_PARAM])
                scope = dict(scope, path=path, raw_path=path.encode("utf-8"),
                             query_string=rest.encode("latin-1"))
        await self.inner(scope, receive, send)


app = _RestoreOriginalPath(fastapi_app)
