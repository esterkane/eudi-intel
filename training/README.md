# training/ — v2 stub (do not implement now)

Fine-tuning is **out of scope for v1** (CLAUDE.md). This directory is a deliberate
seam for later PEFT/TRL + LoRA/QLoRA work. The v1 system is retrieval-first; nothing
in the running app depends on anything here.

When v2 begins, this is where dataset builders, LoRA/QLoRA configs, and TRL training
scripts will live. Keep the v1 build free of dependencies on this directory.
