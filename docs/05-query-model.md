# Query model

A query is a rule plus a partial set of fields, and the result is a list of full field dictionaries, each with a resolvable location. Every key left out of the query acts as a wildcard.

So "give me the media for day14" is the media rule with one key supplied. The caller receives entities, not paths, and asks for a location only when it needs one.

**How a backend answers**

- **Filesystem:** walk the tree one level at a time, pruning with the known keys, then parse each name back into fields. A glob is only a coarse prefilter. The key patterns and choices are the strict check.
- **Database:** compile the criteria into a WHERE clause over the key columns, plus any attribute filters.
- **Object storage:** list by the longest known key prefix, then filter the results.

**Key order is a performance decision.** Filesystems and object stores are prefix-oriented, so a query is cheap when the keys it supplies come first in the rule. Asking for one day is fast if day is an early key, and asking for one camera across every day becomes a scan. A database does not care. Rule authors should order keys by how people actually ask.

**Extension points**

- A base query covers the common case: rule, fields, optional attribute filters, results as fields or locations.
- Small, composable filters and transforms handle the usual needs, such as newest version only, sorting, grouping, or collapsing a numbered sequence into one item.
- Subclassing is available for one-off behavior. Composition is preferred when several variations need to be combined.
- Results carry a flag for provisional entities, so callers can tell authority data from items still in holding.

---

Previous: [Configuration model](04-configuration-model.md) | Next: [Authority and links](06-authority-and-links.md) | [Index](README.md)
