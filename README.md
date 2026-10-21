# Entity Layout & Storage Abstraction

A design plan for a small, storage-neutral layer that lets tools ask for things by name and fields instead of by path, and keeps those things consistent across a filesystem, a database and cloud storage.

- **Read it as a website:** https://peeld.github.io/pipeline-files/
- **Read it on GitHub:** start at [docs/README.md](docs/README.md)

## Building the site locally

```sh
pip install -r requirements-docs.txt
mkdocs serve
```

The site is published to GitHub Pages by [.github/workflows/docs.yml](.github/workflows/docs.yml) on every push to `main`.
