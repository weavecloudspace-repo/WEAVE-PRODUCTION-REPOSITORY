"""Optional Redis acceleration for staff TMA reads; never authorization authority."""

from uuid import uuid4

from app.config.logging import get_logger
from app.core.cache.base import build_cache_key, hash_params, tenant_prefix
from app.core.cache.manager import CacheManager
from app.core.cache.redis import get_redis

logger = get_logger(__name__)


def generation_key(tenant_id):
    return build_cache_key(tenant_prefix(str(tenant_id)), "tma", "v1", "generation")


async def _generation(tenant_id):
    redis = get_redis()
    if redis is None:
        return None
    try:
        key = generation_key(tenant_id)
        # A new random namespace after invalidation prevents an older in-flight
        # read from restoring data used by requests after the committed write.
        await redis.set(key, str(uuid4()), nx=True, ex=86400)
        value = await redis.get(key)
        return value.decode() if isinstance(value, bytes) else value
    except Exception:
        logger.warning("TMA cache generation unavailable", exc_info=True)
        return None


async def cached_staff_read(actor, resource, fetcher, *, params=None, ttl=30):
    version = await _generation(actor.tenant_id)
    if version is None:
        return await fetcher()
    key = build_cache_key(
        tenant_prefix(str(actor.tenant_id)),
        "tma",
        "v1",
        version,
        type(actor).__name__,
        actor.id,
        resource,
        hash_params(params),
    )
    cached = await CacheManager.get_json(key)
    if cached is not None:
        return cached
    # Keep the loader in this request's session rather than sharing an ORM
    # session between requests through get_or_set's background population task.
    result = await fetcher()
    if await _generation(actor.tenant_id) == version:
        await CacheManager.set_json(key, result, ttl)
    return result
