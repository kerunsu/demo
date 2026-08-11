# InteractionProfileV2 compatibility report

## Current guarantee

Runtime first obtains the legacy candidate and only overlays a valid,
published, eligible V2 profile. `inherit` overlays explicit fields;
`replace` starts from the V2 binding; disabled/unmatched/draft/invalid/error
returns legacy. A session freezes the server-selected profile version at the
first real `play_resource`, including an explicit legacy `None` choice, so a
mid-session client value cannot switch behavior.

The context is course-first and carries `courseId`, `courseType`, `sceneKey`,
`eventKey`, `lineId`, session/training IDs and profile version. Naming maps to
`question.naming`; vocal imitation requires explicit course metadata, while
ambiguous generic `mimic` keeps legacy behavior. The catalog has 16 events.

V2 speech is now consumed by the formal play path and uses the existing child
room speech event with correlation IDs. No V2 speech means the old audio path.
Motion/emotion busy gates remain global and do not leak visual commands.

## Remaining acceptance work

Durable shadow reports and front-end authoring/preview for course → event →
scene → line → speech/motion/expression/timing are not a full release feature
yet. They need UI and persistent evidence without changing old course_map
resolution. Publish validation is stronger, but real asset catalog coverage and
manual preview still need operator acceptance.
