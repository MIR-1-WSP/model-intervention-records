# MIR-1 — normative kernel

Standalone form of Appendix D. Normative. Where it and the full specification
differ, the specification governs and the difference is a defect. Written for
automated review pipelines and model context windows.

---

A claim that an intervention changes a model's behavior is, in current practice,
unfalsifiable, because the record of the claim does not state what must not
change. A conforming record carries three mandatory parts: a declared falsifier
that returns a boolean; an invariant set with at least one metric outside the
claim's own declared scoring function; and content-addressed lineage to a base
artifact. Omitting any of the three does not conform, whatever result is reported.

Every run reports the claim's metric as a number, and states its cost and
duration or declares them undisclosed. The record names the claimant and carries
a status its evidence supports: broken lineage is orphan; replicated requires
independent runs by other operators, with disclosed funding differing from the
claimant's.

Conformance is mechanical and permissionless: anyone may run the suite against
any record and publish the outcome, and no body may certify, license, or revoke
it. Four parameters are declared in the registry manifest (challenge window,
bond size, replication count, benchmark rotation) and may be changed only by
forking it; the suite reads the replication count. Replication is an independent
run, not truth.
