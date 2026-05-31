"""
Test suite for the UniAbsences project.

This package contains all automated tests covering:
  - Business logic (absence rates, validation, eligibility).
  - Integration scenarios (signal loops, year deactivation, QR workflows).
  - Security (2FA, CSRF, XSS escaping, upload validation, API isolation).
  - Performance (SQL query budgets for key dashboard views).
  - Infrastructure (health checks, logging, CI migration checks).

Each sub-module groups related tests by feature or concern.  Test data is
created per-test unless ``setUpTestData`` is used for immutable shared fixtures.

Part of the UniAbsences test infrastructure.
"""
