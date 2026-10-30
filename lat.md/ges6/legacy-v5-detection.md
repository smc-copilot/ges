# Legacy v5 Detection

Alpha.1 reports GES v5 from the consumer install lock and never deletes files whose ownership cannot be proven.

Matching `installed_sha256` is removable; missing paths are reported; hash mismatch is `PRESERVE + REPORT`. Logic is [[ges/legacy/v5.py#inspect_legacy]].
