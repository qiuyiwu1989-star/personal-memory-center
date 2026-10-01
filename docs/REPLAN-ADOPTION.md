# Versioned Claude input plans

The owner can generate a no-model preview from a hash-verified conversation archive,
compare segment counts and adopt the input version in the archive panel.
The immutable plan identity includes owner, old batch, archive digest and parser version.
Repeated preview/adoption is idempotent. Adoption records `adopted_waiting_quality`;
it does not dispatch jobs, change budgets, or replace legacy records/segments.

Old record evidence is mapped only within its original conversation/message and
when its exact quote occurs in visible text. Zero matches remain unresolved;
multiple new locators remain ambiguous. These states do not establish factual
accuracy or present validity. Secondary summaries remain separate.

The REST preview response returns at most 25 conversation changes and 25 evidence
mappings per offset, never the complete planned source payload. Only the owner
with the batch scope may inspect it; creation/adoption also require write access.

Next gate: evaluate the difficult cases under one prompt/version, review attribution,
time and scope, then explicitly approve quality and authorize funded dispatch.
This release intentionally supplies no dispatch path for adopted plans.
