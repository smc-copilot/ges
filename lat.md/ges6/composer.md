# Composer

Composer inspects a business repository and installs only the resolved capability closure. It never authors Specs, plans or code.

Pipeline: analyze → resolve → source resolve → harness projection → reconcile. Spec Kit projection comes from official pinned specify-cli staging. After first install the requested set is frozen. Entry points are [[ges/cli/main.py#main]], [[ges/compose.py#compose]] and [[ges/source_adapters/speckit_render.py#official_stage]].
