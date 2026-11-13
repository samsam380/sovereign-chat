# Security and disclosure

This source is intended for self-hosters. It is **not independently audited**.
Do not publish live server state. If you find a vulnerability, coordinate
a private report to the repository maintainer before public disclosure.

The iOS client is based on Element X iOS; preserve the AGPL-3.0 license and
the original upstream notices when redistributing or modifying the source.

Before making a deployed fork public, scan the entire Git history as well as
the working tree for credentials. `.gitignore` prevents new files from being
added but does not remove secrets already committed. Rotate any credential
that has ever been publicly exposed.
