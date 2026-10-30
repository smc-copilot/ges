# Source Resolve

Upstream Matt, Spec Kit and Superpowers trees are fetched only at immutable commit SHAs and cached outside the business repo.

Every cache hit verifies `ges.source-cache-manifest.v1` repo, commit and `content_digest`. Symlinks are rejected. Offline tests set `GES_SOURCE_CACHE` and `GES_SOURCE_OFFLINE=1`. Fetch lives in [[ges/source_adapters/cache.py#ensure_source]].
