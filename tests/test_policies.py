"""Storage policy semantics (ADR-0004)."""

from __future__ import annotations

import pytest

from file_ferry.application.policies import (
    PolicyValidationError,
    default_policy,
    is_stricter_or_equal,
    validate_policy,
    weaker_fields,
)
from file_ferry.service.protocol import StoragePolicy


def test_default_policy_is_the_floor() -> None:
    policy = default_policy()
    assert policy.required_replicas == 2
    assert policy.backup_on_different_volume is True
    assert policy.checksum_algo == "xxhash64"
    assert policy.require_source_fingerprint is True
    assert is_stricter_or_equal(policy)


def test_stricter_policy_is_stricter_or_equal() -> None:
    stricter = StoragePolicy(
        requiredReplicas=3,
        backupOnDifferentVolume=True,
        checksumAlgo="sha256",
        safetyReserveBytes=1024,
        requireSourceFingerprint=True,
    )
    assert is_stricter_or_equal(stricter)
    assert weaker_fields(stricter) == []


def test_weaker_replicas_flagged() -> None:
    weaker = StoragePolicy(
        requiredReplicas=1,
        backupOnDifferentVolume=True,
        checksumAlgo="xxhash64",
        safetyReserveBytes=0,
        requireSourceFingerprint=True,
    )
    assert not is_stricter_or_equal(weaker)
    assert "required_replicas" in weaker_fields(weaker)


def test_same_volume_backup_flagged() -> None:
    weaker = StoragePolicy(
        requiredReplicas=2,
        backupOnDifferentVolume=False,
        checksumAlgo="xxhash64",
        safetyReserveBytes=0,
        requireSourceFingerprint=True,
    )
    assert not is_stricter_or_equal(weaker)
    assert "backup_on_different_volume" in weaker_fields(weaker)


def test_fingerprint_disabled_flagged() -> None:
    weaker = StoragePolicy(
        requiredReplicas=2,
        backupOnDifferentVolume=True,
        checksumAlgo="xxhash64",
        safetyReserveBytes=0,
        requireSourceFingerprint=False,
    )
    assert not is_stricter_or_equal(weaker)
    assert "require_source_fingerprint" in weaker_fields(weaker)


def test_validate_policy_rejects_unacknowledged_weaker() -> None:
    weaker = StoragePolicy(
        requiredReplicas=1,
        backupOnDifferentVolume=True,
        checksumAlgo="xxhash64",
        safetyReserveBytes=0,
        requireSourceFingerprint=True,
    )
    with pytest.raises(PolicyValidationError, match="required_replicas"):
        validate_policy(weaker)


def test_validate_policy_allows_acknowledged_weaker() -> None:
    weaker = StoragePolicy(
        requiredReplicas=1,
        backupOnDifferentVolume=True,
        checksumAlgo="xxhash64",
        safetyReserveBytes=0,
        requireSourceFingerprint=True,
    )
    validate_policy(weaker, acknowledge_weaker=True)  # must not raise


def test_validate_policy_rejects_too_few_replicas() -> None:
    with pytest.raises(ValueError):
        StoragePolicy(
            requiredReplicas=0,
            backupOnDifferentVolume=True,
            checksumAlgo="xxhash64",
            safetyReserveBytes=0,
            requireSourceFingerprint=True,
        )
