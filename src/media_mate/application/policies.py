"""Storage policy and safe-to-format policy semantics.

Freezes ADR-0004: the default policy requires one working + one backup
replica on a different physical volume, using ``xxhash64`` by default.
The default is the *floor*: a user may opt into a stricter policy but
never a hidden weaker one. Weakening below the default requires the
caller to pass ``acknowledge_weaker=True``.

The :class:`StoragePolicy` shape is the wire model defined in
:mod:`media_mate.service.protocol` (camelCase aliases for the IPC and
the self-describing receipt). This module owns the policy *semantics*:
defaults, the floor comparison, and validation.
"""

from __future__ import annotations

from media_mate.service.protocol import StoragePolicy as StoragePolicy

DEFAULT_REQUIRED_REPLICAS = 2
MIN_REQUIRED_REPLICAS = 1


def default_policy() -> StoragePolicy:
    """Return the default, floor policy (ADR-0004)."""
    return StoragePolicy(
        requiredReplicas=DEFAULT_REQUIRED_REPLICAS,
        backupOnDifferentVolume=True,
        checksumAlgo="xxhash64",
        safetyReserveBytes=0,
        requireSourceFingerprint=True,
    )


def is_stricter_or_equal(policy: StoragePolicy, floor: StoragePolicy | None = None) -> bool:
    """Return True if ``policy`` is at least as strict as ``floor``.

    Weaker than the floor means: fewer required replicas than the
    floor, backup on the same volume while the floor requires a
    different volume, or fingerprint verification disabled while the
    floor requires it.
    """
    floor = floor if floor is not None else default_policy()
    replicas_ok = policy.required_replicas >= floor.required_replicas
    backup_ok = not (
        policy.backup_on_different_volume is False and floor.backup_on_different_volume is True
    )
    fingerprint_ok = not (
        policy.require_source_fingerprint is False and floor.require_source_fingerprint is True
    )
    return replicas_ok and backup_ok and fingerprint_ok


def weaker_fields(policy: StoragePolicy, floor: StoragePolicy | None = None) -> list[str]:
    """Return the names of policy fields that are weaker than ``floor``."""
    floor = floor if floor is not None else default_policy()
    out: list[str] = []
    if policy.required_replicas < floor.required_replicas:
        out.append("required_replicas")
    if policy.backup_on_different_volume is False and floor.backup_on_different_volume is True:
        out.append("backup_on_different_volume")
    if policy.require_source_fingerprint is False and floor.require_source_fingerprint is True:
        out.append("require_source_fingerprint")
    return out


def validate_policy(policy: StoragePolicy, *, acknowledge_weaker: bool = False) -> None:
    """Validate a policy before it is persisted.

    Raises :class:`PolicyValidationError` when the policy is weaker
    than the default floor and ``acknowledge_weaker`` is not set.
    """
    weak = weaker_fields(policy)
    if weak and not acknowledge_weaker:
        raise PolicyValidationError(
            f"policy is weaker than the default floor in: {', '.join(weak)}; "
            "weakening below the default requires explicit acknowledgement"
        )


class PolicyValidationError(ValueError):
    """Raised when a storage policy is invalid or unacknowledged weaker."""
