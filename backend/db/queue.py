import os
from redis import Redis
from rq import Queue
from dotenv import load_dotenv

load_dotenv()

_redis_conn = None
_queue = None


def get_queue() -> Queue:
    global _redis_conn, _queue
    if _queue is None:
        _redis_conn = Redis.from_url(os.environ["REDIS_URL"])
        _queue = Queue("ingestion", connection=_redis_conn)
    return _queue
