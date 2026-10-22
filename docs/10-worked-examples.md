# Worked examples

The same model fits five very different fields by changing only the configuration: the keys, the rules, and which backend is the authority. These examples are illustrations, not prescriptions.

| Field | Entity and keys | Authority | Active links | Passive links | Example query |
| --- | --- | --- | --- | --- | --- |
| Visual effects | Shot media: project, sequence, shot, version, camera. Attributes: status, artist, task | Production tracking database | Studio file server, one folder tree per shot | Cloud review and archive copies | Media for shot 040, latest version |
| Data science | Experiment output: project, experiment, run. Attributes: parameters, metrics, author, stage | Experiment tracking database | Shared object storage, one prefix per run | Cold archive after a run is validated | All runs of experiment 12 that reached the validated stage |
| Industrial design | Part revision: product, assembly, part number, revision. Attributes: material, approval, owner | Product data management database | Engineering file share with a sidecar per model | Supplier portal copy on release | Drawings for assembly A12, released revisions only |
| General office | Client deliverable: client, year, quarter, document type. Attributes: author, review status, retention class | Document management system | Team shared drive | Records archive once approved | Approved reports for one client in 2026 |
| Scientific data | Acquisition: study, sample, session, instrument, run. Attributes: parameters, operator, quality flag | Lab information system | Lab storage array | Institutional repository on publication | Raw files for sample S017, session 2, instrument B |

**What stays the same across all five**

- The caller names an entity type and some fields. It never builds a path.
- Keys are the things you would say aloud to find the item. Attributes are everything that changes while the item is worked on.
- The authority is wherever the organization already keeps its record of truth. The file layout follows it.
- Passive links map to a deliberate act: approve, release, publish, archive.

**When the authority is unreachable**

- A visual effects artist on a train keeps rendering, and the new versions sit in holding until the connection returns.
- A data scientist on a cluster with no route to the tracking database writes run outputs to holding and merges them after the job.
- A designer on a flight saves new part revisions locally. Revisions are letters, which a version up cannot raise yet, so a revision someone else released first needs an engineer to decide.
- An office worker offline adds documents to a client folder, and conflicts with a colleague's new file are resolved by suffix.
- A field scientist logs acquisitions on a laptop at a remote site, and the merge assigns sample session numbers on return.

---

Previous: [Conflict resolution](09-conflict-resolution.md) | Next: [Risks and implementation considerations](11-risks-and-implementation-considerations.md) | [Index](README.md)
