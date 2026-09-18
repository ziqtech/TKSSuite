"""Versioned skill-state extension stored after the original save frames.

The embedded game save remains untouched.  New skill learning state and
optional sparse TKKon overrides live in a strict, checksummed envelope after
Frame 2.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, replace
from typing import Iterable, Optional, Tuple


MAGIC = b"TKSX"
VERSION = 1
HEADER_SIZE = 64
OVERRIDE_SIZE = 8
GAME_ACTOR_CAPACITY = 500
GAME_SKILL_CAPACITY = 347
GAME_SKILL_BASE = 350
GAME_EXTENDED_TKKON_DEFAULT = 590
# TKKon.dat itself can be expanded past the original 650 records.  The
# WarPC/TKSX mapping stores the ID as a signed int16, so 32767 is the
# format limit rather than the original file's 650-record capacity.
GAME_TKKON_CAPACITY = 32768
GAME_OVERRIDE_CAPACITY = 64
GAME_MAPPING_VERSION = 1

_HEADER = struct.Struct("<4sHHIIIHHHHHHIHH24s")
_OVERRIDE = struct.Struct("<HHhH")


class SkillExtensionError(ValueError):
    """Base class for skill extension protocol errors."""


class SkillExtensionFormatError(SkillExtensionError):
    """The extension envelope is malformed or fails validation."""


class SkillExtensionVersionError(SkillExtensionError):
    """The extension envelope uses an unsupported version."""


def mod_identity_crc32(identity: str) -> int:
    """Return a stable 32-bit fingerprint for a MOD identity string."""
    return zlib.crc32(identity.encode("utf-8")) & 0xFFFFFFFF


@dataclass(frozen=True)
class SparseSkillOverride:
    actor_id: int
    skill_id: int
    tkkon_id: int
    flags: int = 0


@dataclass(frozen=True)
class SkillExtension:
    actor_count: int
    skill_base: int
    skill_count: int
    learn: bytes
    overrides: Tuple[SparseSkillOverride, ...] = ()
    mod_id: int = 0
    mapping_version: int = GAME_MAPPING_VERSION
    flags: int = 0
    actor_capacity: int = 0
    skill_capacity: int = 0

    def __post_init__(self) -> None:
        self.validate()

    @property
    def stride(self) -> int:
        """Stored bytes per actor row (capacity, not registered count)."""
        return self.skill_capacity or self.skill_count

    def validate(self) -> None:
        if self.actor_count <= 0:
            raise SkillExtensionFormatError("actor_count must be positive")
        if self.actor_count > GAME_ACTOR_CAPACITY:
            raise SkillExtensionFormatError(
                f"actor_count {self.actor_count} exceeds the game capacity "
                f"{GAME_ACTOR_CAPACITY}")
        if self.skill_base != GAME_SKILL_BASE:
            raise SkillExtensionFormatError(
                f"skill_base must be {GAME_SKILL_BASE}")
        if self.skill_count <= 0:
            raise SkillExtensionFormatError("skill_count must be positive")
        if self.skill_count > GAME_SKILL_CAPACITY:
            raise SkillExtensionFormatError(
                f"skill_count {self.skill_count} exceeds the game capacity "
                f"{GAME_SKILL_CAPACITY}")
        if self.actor_capacity and self.actor_capacity < self.actor_count:
            raise SkillExtensionFormatError(
                "actor_capacity is smaller than actor_count")
        if self.skill_capacity and self.skill_capacity < self.skill_count:
            raise SkillExtensionFormatError(
                "skill_capacity is smaller than skill_count")
        if self.actor_capacity > GAME_ACTOR_CAPACITY:
            raise SkillExtensionFormatError(
                f"actor_capacity {self.actor_capacity} exceeds the game capacity")
        if self.skill_capacity > GAME_SKILL_CAPACITY:
            raise SkillExtensionFormatError(
                f"skill_capacity {self.skill_capacity} exceeds the game capacity")
        expected = self.actor_count * self.stride
        if len(self.learn) != expected:
            raise SkillExtensionFormatError(
                f"learn size mismatch: {len(self.learn)} != {expected}")
        if len(self.overrides) > GAME_OVERRIDE_CAPACITY:
            raise SkillExtensionFormatError(
                f"too many sparse overrides: {len(self.overrides)} "
                f"(max {GAME_OVERRIDE_CAPACITY})")

        seen = set()
        skill_end = self.skill_base + self.skill_count
        for entry in self.overrides:
            key = (entry.actor_id, entry.skill_id)
            if key in seen:
                raise SkillExtensionFormatError(
                    f"duplicate override for actor {entry.actor_id}, "
                    f"skill {entry.skill_id}")
            seen.add(key)
            if not 0 <= entry.actor_id < self.actor_count:
                raise SkillExtensionFormatError(
                    f"override actor out of range: {entry.actor_id}")
            if not self.skill_base <= entry.skill_id < skill_end:
                raise SkillExtensionFormatError(
                    f"override skill out of range: {entry.skill_id}")
            if not 0 <= entry.tkkon_id < GAME_TKKON_CAPACITY:
                raise SkillExtensionFormatError(
                    f"override TKKon out of range: {entry.tkkon_id}")
            if entry.flags != 0:
                raise SkillExtensionFormatError(
                    f"override flags out of range: {entry.flags}")

    def learn_state(self, actor_id: int, skill_id: int) -> int:
        self.validate()
        if not 0 <= actor_id < self.actor_count:
            raise SkillExtensionFormatError(
                f"actor out of range: {actor_id}")
        offset = skill_id - self.skill_base
        if not 0 <= offset < self.skill_count:
            raise SkillExtensionFormatError(
                f"skill out of range: {skill_id}")
        return self.learn[actor_id * self.stride + offset]

    def with_learn_state(self, actor_id: int, skill_id: int,
                         state: int) -> "SkillExtension":
        self.validate()
        if not 0 <= state <= 0xFF:
            raise SkillExtensionFormatError(f"state out of range: {state}")
        if not 0 <= actor_id < self.actor_count:
            raise SkillExtensionFormatError(
                f"actor out of range: {actor_id}")
        offset = skill_id - self.skill_base
        if not 0 <= offset < self.skill_count:
            raise SkillExtensionFormatError(
                f"skill out of range: {skill_id}")
        index = actor_id * self.stride + offset
        learn = bytearray(self.learn)
        learn[index] = state
        return replace(self, learn=bytes(learn))

    def with_learn_states(self, updates: Iterable[Tuple[int, int, int]]
                          ) -> "SkillExtension":
        """Apply multiple actor/skill/state updates in one matrix copy."""
        learn = bytearray(self.learn)
        for actor_id, skill_id, state in updates:
            if not 0 <= actor_id < self.actor_count:
                raise SkillExtensionFormatError(
                    f"actor out of range: {actor_id}")
            offset = skill_id - self.skill_base
            if not 0 <= offset < self.skill_count:
                raise SkillExtensionFormatError(
                    f"skill out of range: {skill_id}")
            if not 0 <= state <= 0xFF:
                raise SkillExtensionFormatError(
                    f"state out of range: {state}")
            learn[actor_id * self.stride + offset] = state
        return replace(self, learn=bytes(learn))

    def with_overrides(
            self,
            updates: Iterable[Tuple[int, int, Optional[int]]],
            ) -> "SkillExtension":
        """Apply actor/skill TKKon overrides; None removes an override.

        The on-disk format stores sparse overrides only.  A missing entry
        means the runtime default TKKon (`GAME_EXTENDED_TKKON_DEFAULT`).
        """
        self.validate()
        entries = {
            (entry.actor_id, entry.skill_id): entry
            for entry in self.overrides
        }
        for actor_id, skill_id, tkkon_id in updates:
            if not 0 <= actor_id < self.actor_count:
                raise SkillExtensionFormatError(
                    f"actor out of range: {actor_id}")
            offset = skill_id - self.skill_base
            if not 0 <= offset < self.skill_count:
                raise SkillExtensionFormatError(
                    f"skill out of range: {skill_id}")
            key = (actor_id, skill_id)
            if tkkon_id is None:
                entries.pop(key, None)
                continue
            if not 0 <= tkkon_id < GAME_TKKON_CAPACITY:
                raise SkillExtensionFormatError(
                    f"override TKKon out of range: {tkkon_id}")
            entries[key] = SparseSkillOverride(
                actor_id=actor_id,
                skill_id=skill_id,
                tkkon_id=tkkon_id,
            )
        if len(entries) > GAME_OVERRIDE_CAPACITY:
            raise SkillExtensionFormatError(
                f"too many sparse overrides: {len(entries)} "
                f"(max {GAME_OVERRIDE_CAPACITY})")
        return replace(self, overrides=tuple(sorted(
            entries.values(),
            key=lambda item: (item.actor_id, item.skill_id),
        )))

    def actor_learn_bytes(self, actor_id: int) -> bytes:
        self.validate()
        if not 0 <= actor_id < self.actor_count:
            raise SkillExtensionFormatError(
                f"actor out of range: {actor_id}")
        start = actor_id * self.stride
        return self.learn[start:start + self.stride]

    def with_actor_learn_bytes(self, actor_id: int,
                               values: bytes) -> "SkillExtension":
        self.validate()
        if not 0 <= actor_id < self.actor_count:
            raise SkillExtensionFormatError(
                f"actor out of range: {actor_id}")
        if len(values) != self.stride:
            raise SkillExtensionFormatError(
                f"actor state size mismatch: {len(values)} != {self.stride}")
        learn = bytearray(self.learn)
        start = actor_id * self.stride
        learn[start:start + self.stride] = values
        return replace(self, learn=bytes(learn))

    def swap_actor_learn_states(self, actor_a: int,
                                actor_b: int) -> "SkillExtension":
        self.validate()
        if not (0 <= actor_a < self.actor_count
                and 0 <= actor_b < self.actor_count):
            raise SkillExtensionFormatError("actor swap index out of range")
        if actor_a == actor_b:
            return self
        learn = bytearray(self.learn)
        a_start = actor_a * self.stride
        b_start = actor_b * self.stride
        a_values = bytes(learn[a_start:a_start + self.stride])
        b_values = bytes(learn[b_start:b_start + self.stride])
        learn[a_start:a_start + self.stride] = b_values
        learn[b_start:b_start + self.stride] = a_values
        return replace(self, learn=bytes(learn))

    def swap_actor_overrides(self, actor_a: int,
                             actor_b: int) -> "SkillExtension":
        """Swap all sparse overrides owned by two actors."""
        self.validate()
        if not (0 <= actor_a < self.actor_count
                and 0 <= actor_b < self.actor_count):
            raise SkillExtensionFormatError("actor swap index out of range")
        if actor_a == actor_b:
            return self
        a_entries = tuple(
            entry for entry in self.overrides if entry.actor_id == actor_a)
        b_entries = tuple(
            entry for entry in self.overrides if entry.actor_id == actor_b)
        retained = [
            entry for entry in self.overrides
            if entry.actor_id not in (actor_a, actor_b)
        ]
        retained.extend(replace(entry, actor_id=actor_b)
                        for entry in a_entries)
        retained.extend(replace(entry, actor_id=actor_a)
                        for entry in b_entries)
        return replace(self, overrides=tuple(sorted(
            retained, key=lambda item: (item.actor_id, item.skill_id))))

    def copy_actor_extension(self, source_actor: int,
                             target_actor: int) -> "SkillExtension":
        """Copy one actor's learn row and sparse overrides to another actor."""
        self.validate()
        if not (0 <= source_actor < self.actor_count
                and 0 <= target_actor < self.actor_count):
            raise SkillExtensionFormatError("actor copy index out of range")
        updated = self.with_actor_learn_bytes(
            target_actor, self.actor_learn_bytes(source_actor))
        copied = [
            replace(entry, actor_id=target_actor)
            for entry in self.overrides
            if entry.actor_id == source_actor
        ]
        retained = [
            entry for entry in updated.overrides
            if entry.actor_id != target_actor
        ]
        retained.extend(copied)
        return replace(updated, overrides=tuple(sorted(
            retained, key=lambda item: (item.actor_id, item.skill_id))))

    def copy_actor_overrides(self, source_actor: int,
                             target_actor: int) -> "SkillExtension":
        """Replace one actor's overrides with another actor's overrides."""
        self.validate()
        if not (0 <= source_actor < self.actor_count
                and 0 <= target_actor < self.actor_count):
            raise SkillExtensionFormatError("actor copy index out of range")
        copied = [
            replace(entry, actor_id=target_actor)
            for entry in self.overrides
            if entry.actor_id == source_actor
        ]
        retained = [
            entry for entry in self.overrides
            if entry.actor_id != target_actor
        ]
        retained.extend(copied)
        return replace(self, overrides=tuple(sorted(
            retained, key=lambda item: (item.actor_id, item.skill_id))))

    def replace_actor_overrides_from(
            self, source: "SkillExtension", actor_id: int
            ) -> "SkillExtension":
        """Replace one actor's overrides with the same actor from source."""
        self.validate()
        source.validate()
        if not 0 <= actor_id < self.actor_count:
            raise SkillExtensionFormatError("actor index out of range")
        if actor_id >= source.actor_count:
            raise SkillExtensionFormatError(
                "source actor index out of range")
        retained = [
            entry for entry in self.overrides
            if entry.actor_id != actor_id
        ]
        retained.extend(
            entry for entry in source.overrides
            if entry.actor_id == actor_id
        )
        return replace(self, overrides=tuple(sorted(
            retained, key=lambda item: (item.actor_id, item.skill_id))))

    def clear_actor_overrides(self, actor_id: int) -> "SkillExtension":
        self.validate()
        if not 0 <= actor_id < self.actor_count:
            raise SkillExtensionFormatError("actor index out of range")
        return replace(self, overrides=tuple(
            entry for entry in self.overrides
            if entry.actor_id != actor_id))

    def override_for(self, actor_id: int, skill_id: int
                     ) -> Optional[SparseSkillOverride]:
        self.validate()
        for entry in self.overrides:
            if entry.actor_id == actor_id and entry.skill_id == skill_id:
                return entry
        return None

    def to_bytes(self) -> bytes:
        self.validate()
        entries = sorted(
            self.overrides,
            key=lambda item: (item.actor_id, item.skill_id),
        )
        payload = bytearray(self.learn)
        for entry in entries:
            payload.extend(_OVERRIDE.pack(
                entry.actor_id, entry.skill_id,
                entry.tkkon_id, entry.flags))
        payload_bytes = bytes(payload)
        header = _HEADER.pack(
            MAGIC,
            VERSION,
            HEADER_SIZE,
            len(payload_bytes),
            zlib.crc32(payload_bytes) & 0xFFFFFFFF,
            self.mod_id & 0xFFFFFFFF,
            self.actor_count,
            self.skill_base,
            self.skill_count,
            len(entries),
            self.flags,
            0,
            self.mapping_version & 0xFFFFFFFF,
            self.actor_capacity or self.actor_count,
            self.skill_capacity or self.skill_count,
            b"\0" * 24,
        )
        return header + payload_bytes


def create_skill_extension(actor_count: int, skill_count: int, *,
                           skill_base: int = GAME_SKILL_BASE,
                           mod_id: int = 0,
                           mapping_version: int = GAME_MAPPING_VERSION,
                           flags: int = 0,
                           actor_capacity: int = 0,
                           skill_capacity: int = 0,
                           overrides: Iterable[SparseSkillOverride] = ()
                           ) -> SkillExtension:
    if actor_capacity == 0 and actor_count == GAME_ACTOR_CAPACITY:
        actor_capacity = GAME_ACTOR_CAPACITY
    if skill_capacity == 0 and skill_count == GAME_SKILL_CAPACITY:
        skill_capacity = GAME_SKILL_CAPACITY
    stride = skill_capacity or skill_count
    extension = SkillExtension(
        actor_count=actor_count,
        skill_base=skill_base,
        skill_count=skill_count,
        learn=b"\0" * (actor_count * stride),
        overrides=tuple(overrides),
        mod_id=mod_id,
        mapping_version=mapping_version,
        flags=flags,
        actor_capacity=actor_capacity,
        skill_capacity=skill_capacity,
    )
    extension.validate()
    return extension


def migrate_skill_extension(extension: Optional[SkillExtension], *,
                            actor_count: int,
                            skill_count: int,
                            skill_capacity: Optional[int] = None,
                            skill_base: int = GAME_SKILL_BASE,
                            mod_id: Optional[int] = None,
                            mapping_version: Optional[int] = GAME_MAPPING_VERSION
                            ) -> SkillExtension:
    """Extend an existing state matrix without truncating saved data.

    Missing actors or skills in the current resources are a hard error.  New
    actors and skills are initialized to zero and require an explicit resource
    migration if their initial values should differ.
    """
    target_stride = skill_capacity or skill_count
    if extension is None:
        return create_skill_extension(
            actor_count=actor_count,
            skill_count=skill_count,
            skill_capacity=target_stride,
            skill_base=skill_base,
            mod_id=mod_id or 0,
            mapping_version=(GAME_MAPPING_VERSION
                             if mapping_version is None
                             else mapping_version),
        )

    extension.validate()
    if extension.skill_base != skill_base:
        raise SkillExtensionFormatError(
            f"skill base mismatch: {extension.skill_base} != {skill_base}")
    if extension.actor_count > actor_count:
        raise SkillExtensionFormatError(
            "current character table is smaller than saved extension state")
    if extension.skill_count > skill_count:
        raise SkillExtensionFormatError(
            "current skill definitions are missing saved extension skills")
    merged_mod_id = mod_id if mod_id is not None else extension.mod_id
    if extension.mod_id and mod_id is not None and extension.mod_id != mod_id:
        raise SkillExtensionFormatError(
            f"MOD identity mismatch: {extension.mod_id} != {mod_id}")

    learn = bytearray(actor_count * target_stride)
    for actor_id in range(extension.actor_count):
        src = actor_id * extension.stride
        dst = actor_id * target_stride
        copy_size = min(extension.stride, target_stride)
        learn[dst:dst + copy_size] = extension.learn[src:src + copy_size]

    return SkillExtension(
        actor_count=actor_count,
        skill_base=skill_base,
        skill_count=skill_count,
        learn=bytes(learn),
        overrides=extension.overrides,
        mod_id=merged_mod_id,
        mapping_version=(extension.mapping_version
                         if mapping_version is None else mapping_version),
        flags=extension.flags,
        actor_capacity=max(extension.actor_capacity, actor_count),
        skill_capacity=target_stride,
    )


def migrate_for_original_game(extension: Optional[SkillExtension], *,
                              actor_count: int,
                              skill_count: int,
                              mapping_version: int = GAME_MAPPING_VERSION
                              ) -> SkillExtension:
    """Migrate to the fixed capacities used by the original-game patch."""
    if actor_count > GAME_ACTOR_CAPACITY:
        raise SkillExtensionFormatError(
            f"current character table has {actor_count} rows; "
            f"the original-game patch supports at most {GAME_ACTOR_CAPACITY}")
    if skill_count > GAME_SKILL_CAPACITY:
        raise SkillExtensionFormatError(
            f"current skill table has {skill_count} extension entries; "
            f"the original-game patch supports at most {GAME_SKILL_CAPACITY}")
    if mapping_version != GAME_MAPPING_VERSION:
        raise SkillExtensionFormatError(
            f"original-game saves require mapping_version "
            f"{GAME_MAPPING_VERSION}")
    if extension is not None and extension.mod_id != 0:
        raise SkillExtensionFormatError(
            "original-game saves require mod_id=0")
    if (extension is not None
            and extension.mapping_version != GAME_MAPPING_VERSION):
        raise SkillExtensionFormatError(
            f"original-game saves require mapping_version "
            f"{GAME_MAPPING_VERSION}")
    if extension is not None and extension.flags:
        raise SkillExtensionFormatError(
            "original-game saves require flags=0")
    registered = (
        max(1, min(skill_count, GAME_SKILL_CAPACITY))
        if extension is None
        else extension.skill_count if skill_count <= 0
        else min(skill_count, GAME_SKILL_CAPACITY)
    )
    if extension is None:
        return create_original_game_extension(
            actor_count=actor_count,
            skill_count=registered,
            mapping_version=mapping_version,
        )

    migrated = migrate_skill_extension(
        extension,
        actor_count=GAME_ACTOR_CAPACITY,
        skill_count=registered,
        skill_capacity=GAME_SKILL_CAPACITY,
        mod_id=None,
        mapping_version=mapping_version,
    )
    template = create_original_game_extension(
        actor_count=GAME_ACTOR_CAPACITY,
        skill_count=registered,
        mapping_version=mapping_version,
    )
    learn = bytearray(migrated.learn)
    for actor_id in range(GAME_ACTOR_CAPACITY):
        row = actor_id * GAME_SKILL_CAPACITY
        if actor_id >= extension.actor_count:
            start = 0
        elif extension.skill_count < registered:
            start = extension.skill_count
        else:
            continue
        learn[row + start:row + registered] = \
            template.learn[row + start:row + registered]
    return replace(migrated, learn=bytes(learn))


def create_original_game_extension(*, actor_count: int,
                                   skill_count: int,
                                   apply_defaults: bool = True,
                                   mapping_version: int = GAME_MAPPING_VERSION,
                                   registered_skill_count: Optional[int] = None
                                   ) -> SkillExtension:
    """Create the default matrix expected by the original-game patch."""
    if actor_count > GAME_ACTOR_CAPACITY:
        raise SkillExtensionFormatError(
            f"current character table has {actor_count} rows; "
            f"the original-game patch supports at most {GAME_ACTOR_CAPACITY}")
    if skill_count > GAME_SKILL_CAPACITY:
        raise SkillExtensionFormatError(
            f"current skill table has {skill_count} extension entries; "
            f"the original-game patch supports at most {GAME_SKILL_CAPACITY}")
    registered = max(
        1, min(
            skill_count if registered_skill_count is None
            else registered_skill_count,
            GAME_SKILL_CAPACITY,
        )
    )
    extension = create_skill_extension(
        actor_count=GAME_ACTOR_CAPACITY,
        skill_count=registered,
        skill_capacity=GAME_SKILL_CAPACITY,
        mapping_version=mapping_version,
    )
    if not apply_defaults:
        return extension
    learn = bytearray(extension.learn)
    for actor_id in range(extension.actor_count):
        start = actor_id * extension.stride
        learn[start:start + registered] = b"\x01" * registered
    learn[0:registered] = b"\x0a" * registered
    return replace(extension, learn=bytes(learn))


def parse_skill_extension(data: bytes) -> Optional[SkillExtension]:
    """Parse a strict extension envelope.

    An empty tail means a legacy save.  A non-empty tail that is not a valid
    extension is rejected instead of being silently discarded.
    """
    if not data:
        return None
    if len(data) < HEADER_SIZE:
        raise SkillExtensionFormatError("skill extension header is truncated")

    (magic, version, header_size, payload_size, payload_crc, mod_id,
     actor_count, skill_base, skill_count, override_count, flags, reserved0,
     mapping_version, actor_capacity, skill_capacity,
     reserved1) = _HEADER.unpack_from(data, 0)

    if magic != MAGIC:
        raise SkillExtensionFormatError(
            "unknown trailing data: skill extension magic not found")
    if header_size != HEADER_SIZE:
        raise SkillExtensionFormatError(
            f"unsupported header size: {header_size}")
    if version != VERSION:
        raise SkillExtensionVersionError(
            f"unsupported skill extension version: {version}")
    if reserved1 != b"\0" * 24:
        raise SkillExtensionFormatError("reserved header bytes are not zero")
    if reserved0 != 0:
        raise SkillExtensionFormatError("reserved header word is not zero")

    expected_size = HEADER_SIZE + payload_size
    if len(data) != expected_size:
        raise SkillExtensionFormatError(
            f"extension size mismatch: {len(data)} != {expected_size}")

    payload = data[HEADER_SIZE:]
    if (zlib.crc32(payload) & 0xFFFFFFFF) != payload_crc:
        raise SkillExtensionFormatError("skill extension CRC32 mismatch")

    stride = skill_capacity or skill_count
    learn_size = actor_count * stride
    expected_payload = learn_size + override_count * OVERRIDE_SIZE
    if payload_size != expected_payload:
        raise SkillExtensionFormatError(
            f"extension payload size mismatch: {payload_size} != "
            f"{expected_payload}")

    learn = payload[:learn_size]
    overrides = []
    offset = learn_size
    for _ in range(override_count):
        actor_id, skill_id, tkkon_id, entry_flags = _OVERRIDE.unpack_from(
            payload, offset)
        offset += OVERRIDE_SIZE
        overrides.append(SparseSkillOverride(
            actor_id=actor_id,
            skill_id=skill_id,
            tkkon_id=tkkon_id,
            flags=entry_flags,
        ))

    extension = SkillExtension(
        actor_count=actor_count,
        skill_base=skill_base,
        skill_count=skill_count,
        learn=learn,
        overrides=tuple(overrides),
        mod_id=mod_id,
        mapping_version=mapping_version,
        flags=flags,
        actor_capacity=actor_capacity,
        skill_capacity=skill_capacity,
    )
    extension.validate()
    return extension


__all__ = [
    "MAGIC",
    "VERSION",
    "HEADER_SIZE",
    "OVERRIDE_SIZE",
    "GAME_ACTOR_CAPACITY",
    "GAME_SKILL_CAPACITY",
    "GAME_SKILL_BASE",
    "GAME_EXTENDED_TKKON_DEFAULT",
    "GAME_OVERRIDE_CAPACITY",
    "GAME_TKKON_CAPACITY",
    "GAME_MAPPING_VERSION",
    "SkillExtensionError",
    "SkillExtensionFormatError",
    "SkillExtensionVersionError",
    "SparseSkillOverride",
    "SkillExtension",
    "mod_identity_crc32",
    "create_skill_extension",
    "migrate_skill_extension",
    "migrate_for_original_game",
    "create_original_game_extension",
    "parse_skill_extension",
]
