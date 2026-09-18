# Security

Production requirements:
- signed input URLs;
- strict file size limits;
- content sniffing;
- sandboxed non-root Blender workers;
- CPU/memory/time quotas;
- no shell interpolation from prompts;
- restricted outbound worker network;
- quarantine generated assets until validation passes;
- private-avatar retention/deletion controls.
