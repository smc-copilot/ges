# Reconcile

Installation is desired-versus-current reconciliation. Apply stages outside the consumer, snapshots T0, then commits receipt in the same transaction.

Unknown pre-existing files cannot be first-install UPDATEd. Drifted receipt-owned files that leave Desired State block with `MANAGED_CONTENT_MODIFIED` instead of REMOVE. Check validates GES state and overlay fingerprint schema, not a frozen post-install business HEAD. Check is [[ges/check.py#run_check]].

Business Source Guard v2 is [[large-repo-snapshot]]. Apply captures T0/T1 through [[ges/reconciler/business_guard.py#capture_business_snapshot]] and writes only through [[ges/reconciler/mutation.py#MutationLedger]].
