# Capability Resolver

Alpha.3 discovers providers beside Composer. The plan is ephemeral and RTK is verify-only.

Resolver rules live in [[ges/providers/resolve.py#build_capability_plan]]. The RTK probe is [[ges/providers/rtk.py#probe_rtk]]. Providers load from [[ges/catalog/providers.py#load_providers]], not `capabilities.yaml`. Init recommendation marks are ASCII so Windows consoles can print them. A same-set `ges init` NOOP still refreshes `ges_version` and a stale per-file business fingerprint. `lock.requested` stays frozen. Gate evidence does not read RTK. Slice READY is not claimed unless Golden PASSes.
