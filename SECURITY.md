# Security policy

## Supported deployment boundary

Security Shift Intake v1.1 is a local, single-operator portfolio application. Its
supported boundary is deliberately narrow:

- run one application process on a trusted workstation;
- bind only to `127.0.0.1`, `localhost`, or `::1`;
- keep the browser, SQLite database, page artifacts, and OCR process on that machine;
- use synthetic documents for demonstrations and public evidence;
- treat exported CSV files and local audit records as sensitive artifacts.

The application does not provide authentication, authorization, multi-user isolation,
TLS termination, or a supported multi-worker coordination model. Do not expose it on
a LAN, the public internet, a shared workstation, or an untrusted reverse proxy. Those
deployments are outside the v1.1 security contract even if another component adds a
password or TLS in front of it.

The server validates loopback clients and hosts, derives routing on the server, and
requires revision-bound human approval before export or simulation. These controls
reduce mistakes inside the supported local workflow; they are not a substitute for an
authenticated production security architecture.

## Sensitive data

Real operational sheets can contain personal or security-relevant information. They
must remain under the ignored `private/` tree or another controlled location and must
not be committed. Repository privacy checks detect configured indicators, but they are
heuristics rather than a guarantee that arbitrary sensitive content will be found.

Use the documented purge commands when a local demonstration or real-input session is
finished. Filesystem deletion is logical removal and may not securely erase storage
media, backups, snapshots, or exported copies.

## Reporting a vulnerability

Please report a suspected vulnerability privately to
`jmiltzarek@edu.unisinos.br`. Include the affected commit, reproduction steps, impact,
and any relevant logs with personal data removed. Do not attach real occurrence sheets.

Only the current v1.1 line receives security fixes. Earlier tags remain available as
historical portfolio snapshots.
