# Query model

A query is a rule plus a partial set of fields, and the result is a list of full field dictionaries, each with a resolvable location. Every key left out of the query acts as a wildcard.

So "give me the media for day14" is the media rule with one key supplied. The caller receives entities, not paths, and asks for a location only when it needs one.

**What a query returns.** Each result is an entity: the rule, the full fields, a location URI and a provisional flag. A key left out of the query matches anything, including an optional key being absent. So a query for camera "main" also returns the "main_hero" variant unless the query names a variant. Query values are checked against their keys first, so a mistyped value fails loudly instead of quietly returning nothing.

**How a backend answers**

- **Filesystem:** walk the tree one level at a time, pruning with the known keys, then parse each name back into fields. A glob is only a coarse prefilter. The key patterns and choices are the strict check.
- **Database:** compile the criteria into a WHERE clause over the key columns, plus any attribute filters.
- **Object storage:** list by the longest known key prefix, then filter the results.

**The filesystem walk in practice** ([decision 0010](decisions/0010-filesystem-queries-are-strict.md))

- Where every key in a level's name is known, the walk checks that one name directly and does not list the directory. Otherwise it lists the directory once and parses each name strictly.
- A template with optional groups is walked once for each combination of groups. Each directory is still listed only once per query.
- Names that do not fit the rule, such as `notes.txt`, `.DS_Store` or a version written as `v01` where the rule writes `v001`, are skipped.
- A name that fits the rule in more than one way raises an error. It is never silently read one way or dropped.
- A key whose values could contain `/` cannot be used in a filesystem template, because the filesystem would read it as a directory.
- Names read from disk are compared in Unicode normal form C, so names stored decomposed, as older macOS volumes do, still match.

**Key order is a performance decision.** Filesystems and object stores are prefix-oriented, so a query is cheap when the keys it supplies come first in the rule. Asking for one day is fast if day is an early key, and asking for one camera across every day becomes a scan. A database does not care. Rule authors should order keys by how people actually ask.

**Extension points**

- A base query covers the common case: rule, fields, optional attribute filters, results as fields or locations.
- Small, composable filters and transforms handle the usual needs, such as newest version only, sorting, grouping, or collapsing a numbered sequence into one item.
- Subclassing is available for one-off behavior. Composition is preferred when several variations need to be combined.
- Results carry a flag for provisional entities, so callers can tell authority data from items still in holding.

| Filter | What it does |
| --- | --- |
| `newest(key)` | Keeps the highest value of key among results that agree on every other key, or on a chosen set of keys |
| `sort_by(*keys)` | Sorts by keys in turn. Results missing a key sort first |
| `where(predicate)` | Keeps results for which a function is true |
| `collapse_sequence(key)` | Turns entities that differ only in a numbered key, such as frames, into one sequence with ranges like `1001-1003,1005` |
| `group_by(results, *keys)` | Groups results by key values. It returns groups, so it comes last |

```python
from entitylayout import FilesystemBackend, Query, load_config, newest, sort_by

layout = load_config("layout/")
media = Query("media", {"project": "alpha", "shot": 40}).then(newest("version"), sort_by("camera"))
for entity in media.run(FilesystemBackend(layout)):
    print(entity.fields, layout.real_path(entity.location))
```

The same query is available from the command line, for example `entitylayout layout/ query media project=alpha shot=40 --newest version`.

**Operations are published per backend.** A backend implements only the operations it can, lists them, and fails on any other ([decision 0004](decisions/0004-operations-optional-and-fail-if-missing.md)). The filesystem backend implements `query` and `exists`. It does not store attributes, so a query that filters by attribute fails there.

---

Previous: [Configuration model](04-configuration-model.md) | Next: [Authority and links](06-authority-and-links.md) | [Index](README.md)
