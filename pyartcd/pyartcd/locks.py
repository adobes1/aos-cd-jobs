import enum
import logging
from types import coroutine

from aioredlock import Aioredlock, LockError

from pyartcd import redis


# Defines the pipeline locks managed by Redis
class Lock(enum.Enum):
    OLM_BUNDLE = 'olm-bundle-lock-{version}'
    MIRRORING_RPMS = 'mirroring-rpms-{version}'
    COMPOSE = 'compose-lock-{version}'
    DISTGIT_REBASE = 'distgit-rebase-lock-{version}'
    MASS_REBUILD = 'mass-rebuild-serializer'
    SIGNING = 'signing-lock-{signing_env}'


# This constant defines for each lock type:
# - how many times the lock manager should try to acquire the lock before giving up
# - the sleep interval between two consecutive retries, in seconds
# - a timeout, after which the lock will expire and clear itself
LOCK_POLICY = {
    # olm-bundle: give up after 1 hour
    Lock.OLM_BUNDLE: {
        'retry_count': 36000,
        'retry_delay_min': 0.1,
        'lock_timeout': 60 * 60 * 2,  # 2 hours
    },
    # mirror RPMs: give up after 1 hour
    Lock.MIRRORING_RPMS: {
        'retry_count': 36000,
        'retry_delay_min': 0.1,
        'lock_timeout': 60 * 60 * 3,  # 3 hours
    },
    # compose: give up after 1 hour
    Lock.COMPOSE: {
        'retry_count': 36000,
        'retry_delay_min': 0.1,
        'lock_timeout': 60 * 60 * 6,  # 6 hours
    },
    # github-activity-lock: give up after 1 hour
    Lock.DISTGIT_REBASE: {
        'retry_count': 36000 * 1,
        'retry_delay_min': 0.1,
        'lock_timeout': 60 * 60 * 6,  # 6 hours
    },
    # mass rebuild: give up after 8 hours
    Lock.MASS_REBUILD: {
        'retry_count': 36000 * 8,
        'retry_delay_min': 0.1,
        'lock_timeout': 60 * 60 * 12,  # 12 hours
    },
    # signing: give up after 1 hour
    Lock.SIGNING: {
        'retry_count': 36000,
        'retry_delay_min': 0.1,
        'lock_timeout': 60 * 60 * 1,  # 1 hour
    }
}


class LockManager(Aioredlock):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger('pyartcd')

    @staticmethod
    def from_lock(lock: Lock, use_ssl=True):
        """
        Builds and returns a new aioredlock.Aioredlock instance. Requires following env vars to be defined:
        - REDIS_SERVER_PASSWORD: authentication token to the Redis server
        - REDIS_HOST: hostname where Redis is deployed
        - REDIS_PORT: port where Redis is exposed

        If use_ssl is set, we assume Redis server is using a secure connection, and the protocol will be rediss://
        Otherwise, it will fall back to the unsecure redis://

        'lock' identifies the desired lock from an Enum class. Each lock is associated with a 'lock_policy' object;
        'lock_policy' is a dictionary that maps the behavioral features of the lock manager.
         It needs to be structured as:

        lock_policy = {
            'retry_count': int,
            'retry_delay_min': float,
            'lock_timeout': float
        }

        where:
        - lock_timeout represents the expiration date in seconds
          of all the locks instantiated on this LockManager instance.
        - retry_count is the number of attempts to acquire the lock.
          If exceeded, the lock operation will throw an Exception
        - retry_delay is the delay time in seconds between two consecutive attempts to acquire a resource

        Altogether, if the resource cannot be acquired in (retry_count * retry_delay), the lock operation will fail.
        """

        lock_policy = LOCK_POLICY[lock]
        return LockManager(
            [redis.redis_url(use_ssl)],
            internal_lock_timeout=lock_policy['lock_timeout'],
            retry_count=lock_policy['retry_count'],
            retry_delay_min=lock_policy['retry_delay_min']
        )

    async def lock(self, resource, *args):
        self.logger.info('Trying to acquire lock %s', resource)
        lock = await super().lock(resource, *args)
        self.logger.info('Acquired resource %s', lock.resource)
        return lock

    async def unlock(self, lock):
        self.logger.info('Releasing lock "%s"', lock.resource)
        await super().unlock(lock)
        self.logger.info('Lock released')


async def run_with_lock(coro: coroutine, lock: Lock, lock_name: str, skip_if_locked: bool = False):
    """
    Tries to acquire a lock then awaits the provided coroutine object
    :param coro: coroutine to be awaited
    :param lock: enum object of Lock kind
    :param lock_name: string to be attached to the lock object
    :param skip_if_locked: do not wait if resource is already locked, just skip the task
    """

    lock_manager = LockManager.from_lock(lock)

    try:
        if skip_if_locked and await lock_manager.is_locked(lock_name):
            lock_manager.logger.info('Looks like there is another task ongoing -- skipping for this run')
            coro.close()
            return

        async with await lock_manager.lock(lock_name):
            return await coro

    except LockError as e:
        lock_manager.logger.error('Failed acquiring lock %s: %s', e)
        raise

    finally:
        await lock_manager.destroy()
