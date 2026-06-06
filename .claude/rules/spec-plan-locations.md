# Spec & plan locations

Superpowers skills default to `docs/superpowers/<kind>/`; in this repo use `docs/<kind>/` instead (flat tree):

- Spec (brainstorming): `docs/specs/<serial_no>-<topic>-design.md`
- Plan (writing-plans): `docs/plans/<serial_no>-<feature>.md`

`<serial_no>` is a 5-digit zero-padded counter (`00000`, `00001`, …); the next is one above the highest in `docs/specs/`. A plan reuses its spec's serial.
