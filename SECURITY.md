# Security policy

## Supported deployment

Security Shift Intake v1.1 is a local, single-operator application. The supported deployment is
one application process with one worker on a trusted workstation, bound only to `127.0.0.1`,
`localhost`, or `::1`.

Keep the browser, SQLite database, page artifacts, OCR process, and exported files on that
machine. Use synthetic documents for demonstrations and public evidence. Treat every real input,
transcription, audit record, screenshot, and export as sensitive.

Do not expose the application on a LAN, the public internet, a shared workstation, or an
untrusted reverse proxy. Adding a password or TLS in front of the current server does not make
such a deployment supported; the application itself has no authenticated user or authorization
model.

## Controls inside that boundary

The server:

- rejects non-loopback clients and untrusted host headers;
- rejects cross-site state-changing requests and requires the revision and state hash loaded by
  the reviewer;
- applies request-body limits, strict form parsing, output escaping, and a restrictive content
  security policy;
- disables public OpenAPI documentation and prevents sensitive dynamic responses from being
  cached;
- serves scripts, styles, and fonts locally without a CDN;
- confines page-image keys to the private artifact root and verifies the stored bytes, SHA-256,
  width, and height;
- derives routing on the server and never trusts client-supplied recipients;
- recalculates readiness under the draft lock before approval, export, or simulation;
- neutralizes spreadsheet formula-control prefixes in CSV cells; and
- records revision snapshots and audit events for state transitions.

These controls reduce mistakes and browser-origin attacks inside the supported local workflow.
They are not a substitute for an authenticated production architecture.

## Unsupported security properties

The v1.1 application does not provide:

- authentication, authorization, roles, or tenant isolation;
- TLS termination or a supported proxy configuration;
- multi-user or multi-worker coordination;
- cross-process locking or a distributed job queue;
- encrypted database or artifact storage;
- secure deletion, backup management, or retention enforcement;
- malware scanning or content disarmament for uploads;
- real delivery or receipt verification.

Anyone who can reach the application port can request document state. Anyone with access to the
local files can read the database and page artifacts. Operating-system permissions and physical
access controls remain the operator's responsibility.

## Safe local operation

1. Run the server through the documented entrypoint; do not add an external bind flag.
2. Verify the URL uses loopback before opening a real document.
3. Keep real inputs under the ignored `private/` boundary.
4. Do not run untrusted browser extensions in the review profile.
5. Review classification and routing before approval, and verify the intended destination of an
   exported CSV outside the application.
6. Stop the server and use the scoped purge commands when the session is complete.

Purge is logical removal, not secure erasure. It cannot remove storage remnants, backups,
snapshots, synchronized copies, browser captures, or exports.

## Supported versions

Security fixes target the current v1.1 line. Earlier tags remain historical portfolio snapshots
and do not receive backports.

## Report a vulnerability

Report suspected vulnerabilities privately to `jmiltzarek@edu.unisinos.br`. Include the
affected commit, reproduction steps, expected and observed behavior, and impact. Remove personal
or operational data from logs and screenshots. Do not attach a real occurrence sheet.

Do not open a public issue before the report has been reviewed when disclosure could expose
sensitive document content or a working exploit.
