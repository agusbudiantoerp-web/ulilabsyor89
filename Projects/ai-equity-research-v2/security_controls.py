"""Server-side role permissions and tamper-evident audit event storage.

OIDC identity verification and immutable issuer-bound principal resolution live in
auth.py. This module enforces the server-managed role map supplied by that layer
and provides the shared audit log; it is not an identity provider.
""" 
